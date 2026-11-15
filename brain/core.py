"""The brain's state machine: bus messages and screen commands in, section 5 state out.

No sockets here (brain/main.py has them), so every rule can be tested with a
fake clock. Times are board epoch ms, the same clock as the bus's recv_t.

Link health (brain/health.py), the x-ray and objects (brain/xray.py) and the
check-in and alert (brain/alert.py) are separate modules; this file feeds them
and puts their output into the state. Still to come, each with its own issue:
recalibration and drift, advice, and the narrator's enter/exit events.
"""
from __future__ import annotations

import json
import logging
import math
import os
import pickle
import re
import statistics
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

from advisor.advise import advise
from brain import features as F
from brain import layout
from brain import settings as S
from brain.alert import Armed, Tamper, Watch
from brain.hall import Hall
from brain.health import Health
from brain.lesson import Lesson
from brain.train import Model
from brain.xray import Xray

BASELINE_MS = 20_000
PASSER_PAUSE_MS = 3_000   # somebody in the camera's view but outside the layout pauses a capture this long at most
BASELINE_GIVE_UP_MS = 120_000   # a baseline asked for by hand that still can't start after this long is dropped
HOME = "S-home"
NODES_JSON = layout.NODES_JSON   # radio/nodes.json
CAM_SILENT_MS = 3_000
TEACHER_FRESH_MS = 1_000
LINK_FRESH_MS = 1_000
WIFI = "pi5>unoq:wifi"
SETTLE_MS = 3_000        # after router_home, pi5 links must sit near base this long
SETTLE_DB = 1.0          # ... within this of base, else an automatic baseline runs
ADVICE_MEDIAN_MS = 3_000 # before_dbm and after_dbm are medians over this long
AFTER_START_MS = 2_000   # after_dbm starts this long after router_moved
HOTSPOT_RECEIVERS = ("pi5b",)   # receivers with no cable (Pi B): their readings ride the sensing Wi-Fi
SAME_OBJECT_M = 0.5      # an advice this close to the one showing is about the same object (the x-ray's match)
TRAIN_PURPOSES = ("train", "object")
TRAIN_KEEP = 8           # a fit reads the newest this-many recordings of each kind (person, empty, object):
                         # room for 3+ walkers with two walks each, and a bound on an afternoon of lessons
EVENT_INFO = ("zone", "link", "node", "before_dbm", "after_dbm", "on", "session", "why")   # contracts/schemas/event.json
GONE_READINGS = 8        # a link is gone, not just slow, once silent for this many readings at its own rate
SUSPECT_DB = 2.0         # the empty level stops following a crossing line once the lines are this far down ...
UNSTICK_MS = 30_000      # ... unless the model has said "nobody" all through a dip this long: then that is the new empty
DRIFT_NOTE_MS = 10_000   # the followed level is noted for the recordings this often, when it has moved
DRIFT_NOTE_DB = 0.5
STAY_DB = 3.0            # somebody who was there stays while the crossing lines are still this far down (settings.stay_x_quiet)
SILENT_MS = 3_000        # a baseline restarts only for a link with no reading for this long
# A layout with a presence line ("presence" in nodes.json). These are the defaults for the keys it may carry:
# the kit's own numbers go in the file, not here.
OBJECT_DB = 3.0          # object_db: a thing left in the line takes at least this off it ...
OBJECT_MAX_DB = 10.0     # object_max_db: ... and less than this (a person took 13.5 to 24 dB on the kit); null = no limit
OBJECT_SPREAD_DB = 1.0   # object_spread_db: ... with the line as steady as when the spot is empty (its 2 s spread)
OBJECT_HOLD_S = 3.0      # object_hold_s: ... for this long
MOVING_SPREAD_DB = 2.0   # moving_spread_db: a person is moving when the line's 2 s spread is this or more
STILL_SHARE = 0.8        # still_spread_db: ... and still again once it is under this; the default is this share of that
MOTION_HOLD_S = 1.5      # motion_hold_s: the spread has to stay over the one, or under the other, this long before the word changes
SPREAD_MS = 2_000        # the spread is taken over this long, and never over readings from before the person stood there
CHECKIN_RETURN_S = 8.0   # checkin_return_s: stepping out of the line and back within this long, while the alert is up, is the check-in
THING_GRACE_MS = 1_000   # a thing in the line stays one for this long after the line stops looking like it
ADVICE_KEEP_MS = 10_000  # the advice about a thing in the line stays this long once the gain has been measured
LABEL_MODES = ("person", "object", "off")
CAM_STATES = ("on", "off", "stalled")


def read_session(path, since_t=None) -> List[dict]:
    """The rssi and label messages of a session file written by the bus.

    since_t: only messages received from then on. The bus appends, so a session name used
    twice holds both recordings; the meta's recv_t picks out the one that was asked for.
    """
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                msg = json.loads(line)
            except ValueError:
                continue   # a line cut short by a crash
            if isinstance(msg, dict) and msg.get("type") in ("rssi", "label") and "recv_t" in msg \
                    and (since_t is None or msg["recv_t"] >= since_t):
                out.append(msg)
    return out


def last_meta(path) -> Optional[dict]:
    """The meta line of the newest recording in a session file, or None."""
    found = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if '"meta"' not in line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") == "meta":
                    found = msg
    except OSError:
        return None
    return found


def base_at(history: List[dict], t) -> Optional[Dict[str, float]]:
    """The baseline in force at time t: the last one taken at or before it. None when unknown
    (the caller then uses the current baseline)."""
    found = None
    for entry in history:
        if t is not None and entry["t"] <= t:
            found = entry["base"]
    return found


def _ends(link: str):
    """'pi5>unoq:wifi' -> ('pi5', 'unoq')."""
    tx, _, rest = link.partition(">")
    return tx, rest.partition(":")[0]


def _same_object(a, b) -> bool:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= SAME_OBJECT_M


def _is_reading(dbm) -> bool:
    return isinstance(dbm, (int, float)) and not isinstance(dbm, bool) and math.isfinite(dbm)


def _is_label(msg: dict) -> bool:
    """A camera label whose zone and persons_in_frame are whole numbers or null."""
    return all(v is None or (isinstance(v, int) and not isinstance(v, bool))
               for v in (msg.get("zone"), msg.get("persons_in_frame")))


def now_ms() -> int:
    return int(time.time() * 1000)


CHAIN_HASH = re.compile(r"^[0-9a-f]{64}$")
CHAIN_FRESH_S = 15.0   # state.chain is left out once no chain head has been heard for this long


class Brain:
    def __init__(self, clock: Optional[Callable[[], int]] = None, to_bus=None, mode_file=None,
                 spawn=None, board_stats=None, links=None, nodes=None, led=None, sessions_dir=None,
                 settings: Optional[S.Settings] = None):
        """clock None = follow the feed (latest recv_t), for recorded files played fast.
        to_bus(msg) forwards a command to the bus.
        spawn(fit, done) runs fit() off the loop, then done(model) back on it.
        nodes is radio/nodes.json, already parsed (default: the repo's copy).
        led is the LED grid (brain/alert.py); None = no lights.
        sessions_dir is data/sessions: baseline.json is written there and read back at start.
        settings: the people rules' numbers (brain/settings.py); None = its defaults, or the
        file named in RADIO_SIGHT_SETTINGS."""
        self.settings = settings or S.load()
        nodes = nodes or json.loads(NODES_JSON.read_text(encoding="utf-8"))
        # The layout is whatever radio/nodes.json says: links (in its order), zones, the router.
        links = tuple(links or [link["id"] for link in nodes["links"]])
        self.zone_ids = [int(z["id"]) for z in nodes["zones"]]
        self.router_node = next((n["id"] for n in nodes["nodes"] if "router" in n.get("roles", [])), "pi5")
        ends = {link["id"]: (link.get("tx"), link.get("rx")) for link in nodes["links"]}
        self.router_links = [k for k in links if self.router_node in ends.get(k, _ends(k))]
        # Links heard by a receiver whose readings travel over the sensing hotspot itself can go
        # quiet when that link is blocked on purpose: they show stale or blind in their own rows
        # but never blind the sensor (desk layout, Pi B).
        over_hotspot = [k for k in links if ends.get(k, _ends(k))[1] in HOTSPOT_RECEIVERS]
        # Section 3: a link with "classifier": false is too thin to classify on. It is read, listed in
        # state.links, judged stale or blind in its own row and counted for tamper like any other,
        # but it is no feature, never blinds the sensor, never holds up a baseline, and the x-ray,
        # objects, the check-in and the advice don't look at it.
        thin = {link["id"] for link in nodes["links"] if link.get("classifier") is False}
        # The layout's presence line is the main sensor: an older "classifier": false on it (written when Wi-Fi
        # did not react to a person, with Pi A off to the side) must not switch it off. It is said, and ignored.
        main_line = (nodes.get("presence") or {}).get("line")
        if main_line in thin:
            logging.getLogger("brain").warning(
                '%s is the presence line of this layout: its "classifier": false is ignored', main_line)
            thin.discard(main_line)
        self.model_links = tuple(k for k in links if k not in thin)
        # The lines a person on the spot stands in, when the layout marks them ("crosses_spot": true).
        self.crossing = tuple(link["id"] for link in nodes["links"]
                              if link.get("crosses_spot") is True and link["id"] in self.model_links)
        self.health = Health.from_nodes(
            nodes, classifier_links=[k for k in self.model_links if k not in over_hotspot])
        self.xray = Xray.from_nodes(dict(nodes, links=[k for k in nodes["links"] if k["id"] not in thin]))
        self.router_links = [k for k in self.router_links if k not in thin]   # the 3 s check after router_home
        self.hall = Hall.from_nodes(nodes)    # optional long links (brain/hall.py); none unless nodes.json lists them
        # On a layout that marks the lines crossing the spot, moving and still are told apart on few, slow
        # lines, and a short run of "moving" is often wrong: the still timer wants spot_moving_run of them.
        crossing = any(link.get("crosses_spot") is True for link in nodes["links"])
        self.watch = Watch({z["id"]: z.get("still_alert_s") for z in nodes["zones"]}, led,
                           self.settings.with_(moving_run=self.settings.spot_moving_run) if crossing else self.settings)
        # after hours: a person who appears and is still there armed.hold_s later is an intrusion
        self.armed = Armed(self.settings, S.hold_s(nodes))
        self.tamper = Tamper.from_nodes(nodes, silent_ms=self.settings.tamper_silent_ms,
                                        clear_ms=self.settings.tamper_clear_ms)   # ... and a device going silent is tampering
        # The optional hall beacons (nodes.json "hall"): not core links, but tamper counts them.
        self._hall_nodes = {b.get("node") for b in (nodes.get("hall") or {}).get("beacons") or []}
        self._hall_seen: Dict[str, Dict[str, int]] = {}   # hall beacon -> {its link: recv_t of the last reading}
        self._heard = set()                   # links with at least one reading
        self._last_seen: Dict[str, int] = {}  # link -> recv_t of its last reading
        self._last_dbm: Dict[str, float] = {} # link -> the last dbm we sent (or its last reading)
        self._health_ok = True
        self._quiet: List[str] = []           # links that can blind the sensor and are stale right now
        self.nodes = nodes
        self._recent: Dict[str, deque] = {link: deque() for link in links}   # (recv_t, dbm), last 10 s
        self.advice: Optional[dict] = None
        self._dismissed: Optional[list] = None    # xy_m of an advice that reset cleared
        self._moved_t: Optional[int] = None       # when router_moved came
        self.settle: Optional[int] = None         # when router_home came, while its 3 s check runs
        self.recalibrating = False                # the automatic baseline after a failed check
        self._old_base: Dict[str, float] = {}
        # "presence" in nodes.json: one line decides whether somebody is there (the gate: the Wi-Fi line from
        # Pi A to Pi B, which fell 15 to 21 dB with a person on the kit and under 1 dB empty). Its 1 s
        # median drop turns presence on at on_db and off under off_db.
        rule = nodes.get("presence") or {}
        self.presence_line = rule.get("line") if rule.get("line") in self.model_links else None
        # No second opinion: on the kit the Bluetooth lines dipped 9 to 20 dB with nobody there, so "second"
        # in the file is read and not used. While the line is silent its last word stands for second_hold_s.
        self.presence_second = None
        if self.presence_line:
            # The sensor is that one line. Health is blind only when it is silent or stale; the level of a
            # Bluetooth line, or of a line that does not cross the spot, never blinds (they dip and drift by
            # themselves), and a line going quiet still shows in its own row and counts for tamper.
            self.health.classifier_links = [self.presence_line]
            self.health.judge_level = False
        # The lines the lean-aside check-in and the drift follow read: the presence line alone where the layout
        # names one (the Bluetooth lines dip 12 to 20 dB by themselves and would fake a lean or stall the follow),
        # else every line marked as crossing the spot.
        self.sense = (self.presence_line,) if self.presence_line else self.crossing
        self.presence_on_db, self.presence_off_db = float(rule.get("on_db", 7.0)), float(rule.get("off_db", 4.0))
        self.presence_hold_ms = int(float(rule.get("second_hold_s", 5.0)) * 1000)
        self._line_present, self._line_seen = False, None
        # A thing left standing in that line: down object_db or more (and less than a person takes), as steady
        # as the empty line, for object_hold_s. And where moving begins: the line's 2 s spread.
        self.object_db = float(rule.get("object_db", OBJECT_DB))
        top = rule.get("object_max_db", OBJECT_MAX_DB)
        self.object_max_db = math.inf if top is None else float(top)
        self.object_spread_db = float(rule.get("object_spread_db", OBJECT_SPREAD_DB))
        self.object_hold_ms = int(float(rule.get("object_hold_s", OBJECT_HOLD_S)) * 1000)
        self.moving_spread_db = float(rule.get("moving_spread_db", MOVING_SPREAD_DB))
        # Still again under still_spread_db (never over the boundary itself), and either way only once the
        # spread has stayed there for motion_hold_s: a person standing still sways, and one sway is not moving.
        self.still_share = min(1.0, float(rule.get("still_spread_db", self.moving_spread_db * STILL_SHARE)) / self.moving_spread_db)
        self.motion_hold_ms = int(float(rule.get("motion_hold_s", MOTION_HOLD_S)) * 1000)
        self._motion_since: Optional[int] = None   # since when the spread has been on the other side of the word
        self._here_t: Optional[int] = None         # since when the line has said somebody is there
        if self.presence_line:
            # One spot, one line: the no-movement alert follows that line's own decision, tick for tick
            # (brain/alert.py, Watch.line), and the check-in is stepping out of the line and back.
            self.watch.line = {"link": self.presence_line,
                               "return_ms": int(float(rule.get("checkin_return_s", CHECKIN_RETURN_S)) * 1000)}
        self._thing = False                        # the decision is "a thing in the line"
        self._thing_since: Optional[int] = None    # since when the line has looked like one
        self._thing_lost: Optional[int] = None     # since when it has stopped looking like one
        self._moving = False                       # the last word on moving / still from the line's spread
        self._gone_t: Optional[int] = None         # when the thing the advice is about was taken away
        self._measured_t: Optional[int] = None     # when the gain from that was measured
        self._drift_t: Optional[int] = None        # when the empty level last followed the crossing lines
        self._suspect_t: Optional[int] = None      # since when those lines have been down with the model saying nobody
        self._noted = (0, {})                      # (when, the levels) last noted for the recordings
        self._said_zone = 0                        # the zone last announced (0 = nobody)
        self._next_zone = (0, 0)                   # (a different zone, decisions in a row)
        self._said_cam = "off"                     # the camera state last announced
        self.sessions_dir = Path(sessions_dir) if sessions_dir else None
        self.want_session: Optional[str] = None   # the id from record_start
        self.raw_kind: Optional[str] = None   # the classifier's kind, even while pred is withheld
        self._raw: Optional[dict] = None
        self._fresh = False
        self._clock = clock
        self.to_bus = to_bus or (lambda msg: None)
        self.mode_file = mode_file
        self.spawn = spawn or (lambda fit, done: done(fit()))
        self.board_stats = board_stats or (lambda: {"cpu_temp_c": None, "cpu_mhz": None, "cpu_pct": None})
        self.links = tuple(links)
        self.feed_t = 0
        self.src = "live"
        self.base: Dict[str, float] = {}
        self._base_log: List[dict] = []       # every baseline of this run, when nothing is written to disk
        self.place_t: Optional[int] = None    # when the operator's last baseline finished: "this place"
        self.expected_hz: Dict[str, float] = {}
        self.quiet_db: Dict[str, float] = {}  # link -> the std of its 0.5 s means over the baseline capture
        self.windower: Optional[F.Windower] = None
        self.window: Optional[dict] = None
        self.capture: Optional[dict] = None   # a running baseline capture
        self._wait_said = ()                  # what the log last said the capture is waiting for
        self.model: Optional[Model] = None
        self.model_n = 0
        self.training: Optional[dict] = None
        self.lesson = Lesson()                # the live lesson (brain/lesson.py)
        self.decision_ms: deque = deque(maxlen=200)
        self.pred: Optional[dict] = None
        self.sessions: Dict[str, dict] = {}
        self.open_session: Optional[dict] = None
        self.router = HOME
        self.label_mode = "off"
        self.truth = None
        self.cam = None        # (recv_t, state)
        self.label = None      # the latest camera label
        self.narration = None
        self.chain = None            # (when heard, state.chain): the board's last chain head
        self.events: List[dict] = []
        self._seq = 0       # one counter for everything we send to the screens (section 4)
        self._cmd_seq = 0   # and one for the commands we pass to the bus, a separate socket
        self._event_n = 0
        self._scanned: Dict[str, tuple] = {}   # session files read and not taken: name -> (mtime, size, place)
        self._load_baseline()
        self._load_model()
        self._load_armed()

    def now(self) -> int:
        return self._clock() if self._clock else self.feed_t

    def _chain_heard(self, msg: dict) -> None:
        """Keep the board's chain head as state.chain: {seq, hash8, verified, witnesses_ok, witnesses}.
        A head that is not one (no record number, no hash) is dropped. verified is true only once
        the board has said so."""
        seq, digest = msg.get("seq"), msg.get("hash")
        counts = [msg.get("witnesses_ok", 0), msg.get("witnesses", 0)]
        if type(seq) is not int or seq < 0 or not isinstance(digest, str) or not CHAIN_HASH.match(digest) \
                or any(type(n) is not int or n < 0 for n in counts):
            return
        self.chain = (time.monotonic(), {"seq": seq, "hash8": digest[:8], "verified": msg.get("verified") is True,
                                         "witnesses_ok": counts[0], "witnesses": counts[1]})

    # ---- inputs ----

    def on_message(self, msg: dict) -> None:
        """One message forwarded by the bus (it carries recv_t)."""
        if msg.get("type") in ("chain_head", "chain_witness"):
            # The sealed record (section 13). Its head is only copied into state; it is not a
            # reading, so it moves no clock and reaches no rule.
            if msg["type"] == "chain_head":
                self._chain_heard(msg)
            return
        if self.hall.take(msg):
            self._hall_heard(msg)   # tamper counts a hall beacon once it has been heard since arming
            return   # a hall link's reading: nothing below ever sees it
        t, kind = msg.get("recv_t"), msg.get("type")
        if t is None:
            return
        if kind == "rssi" and not (_is_reading(msg.get("dbm")) and isinstance(msg.get("link"), str)):
            return   # no number, NaN (JSON lets it through) or a link that isn't a name: never used
        if kind == "label" and not _is_label(msg):
            return   # a zone or a count that isn't a number: the windows would choke on it
        self.feed_t = max(self.feed_t, int(t))
        if kind == "rssi":
            self._hall_heard(msg)
        if kind == "rssi":
            # state.src mirrors the radio feed. The camera and the bus's meta say "live"
            # even over a sim feed, and must not flip the screen's badge to LIVE.
            self.src = msg.get("src", self.src)
        if kind == "meta":
            # Only the meta the bus writes for our record_start opens a copy. The fake
            # feed sends its own meta (and again on every loop); those are ignored.
            if self.want_session is not None and msg.get("session") == self.want_session:
                # Only recordings that training reads are held, and only until record_stop
                # finds the bus's file on disk. A long demo recording costs no memory.
                keep = msg.get("purpose") in TRAIN_PURPOSES
                # The bus opens its file before it sends this meta, so on the board nothing is
                # held here at all, however long the recording runs.
                held = keep and self._session_path(msg.get("session")) is None
                self.open_session = {"meta": msg, "keep": keep, "messages": [] if held else None}
        elif kind == "cam":
            if msg.get("state") in CAM_STATES:   # anything else would go to the screen as it came
                self.cam = (t, msg["state"])
        elif kind == "narration":
            # Shown as it is, so it has to be showable: a sentence, and the event it is about.
            if isinstance(msg.get("text"), str) and isinstance(msg.get("event_id"), str) \
                    and msg.get("source") in ("llm", "template"):
                self.narration = {k: msg.get(k) for k in ("text", "event_id", "t", "source", "gen_ms")}
        elif kind in ("rssi", "label"):
            if self.open_session is not None and self.open_session["messages"] is not None:
                self.open_session["messages"].append(msg)
            if kind == "label":
                self.label = msg
            elif msg.get("link") in self.links:
                link, dbm = msg["link"], float(msg["dbm"])
                self.health.add(link, t, dbm)
                if link in self.model_links:
                    self.watch.on_rssi(msg)
                self._heard.add(link)
                self._last_seen[link] = t
                self._last_dbm.setdefault(link, dbm)
                recent = self._recent[link]
                recent.append((t, dbm))
                while recent[0][0] < t - 10_000:
                    recent.popleft()
                if link in self.base:
                    self.xray.add(link, t, self.base[link] - dbm)
                if self.capture and self.capture["start"] is not None and self.capture["paused"] is None:
                    self.capture["messages"].append(msg)
            if self.windower:
                for window in self.windower.push(msg):
                    self.window = window
        self._tick()

    def _hall_heard(self, msg: dict) -> None:
        """Remember when a hall beacon's link was last heard, for tamper. Nothing else uses it."""
        link, t = msg.get("link"), msg.get("recv_t")
        if not (self._hall_nodes and isinstance(link, str) and isinstance(t, (int, float))
                and _is_reading(msg.get("dbm"))):
            return
        tx = _ends(link)[0]
        if tx in self._hall_nodes and link not in self.links:
            self._hall_seen.setdefault(tx, {})[link] = int(t)

    def on_cmd(self, msg: dict) -> None:
        """One command from the screen. Every command also goes to the bus, which records it."""
        cmd, args = msg.get("cmd"), msg.get("args") or {}
        handler = getattr(self, f"_cmd_{cmd}", None) if isinstance(cmd, str) else None
        if handler is None or not isinstance(args, dict):
            return   # not a command we know, or args that aren't an object: dropped
        self._cmd_seq += 1
        self.to_bus({"v": 2, "type": "cmd", "t": self.now(), "seq": self._cmd_seq, "src": self.src,
                     "cmd": cmd, "args": args})
        handler(args)

    def _cmd_baseline(self, args):
        """A baseline asked for by hand means a new place (or a new layout): when it finishes, the
        model and the recordings made before it are dropped from use. The files stay on disk.

        baseline {keep_model: true} = the same layout set down again (another desk, a knocked
        beacon): only the baseline is new. The model was taught on drops from a baseline, so
        it carries over, and the recordings keep the baseline they were made on."""
        new_place = args.get("keep_model") is not True
        if self.capture and self.capture["by_hand"] and self.capture["new_place"] == new_place:
            return   # a double tap, or two operator pages: the capture already running carries on (#649)
        self._cmd_label_mode({"mode": "off"})
        self._start_capture(new_place=new_place, by_hand=True)

    def _newest_recordings(self) -> List[dict]:
        """The recordings a fit reads: the newest TRAIN_KEEP of each kind, not all of them.

        Every judge's lesson leaves one more train recording in this place, and a fit read them
        all, so fits (and the 30 s lesson) grew all afternoon (#611). Kinds are kept apart so a
        run of lessons can't push out the empty-room or the tray recordings: walks with a walker,
        train recordings without one (the empty room), and object recordings. The files stay on
        disk; a new place still starts from none.
        """
        kinds: Dict[str, List[dict]] = {"person": [], "empty": [], "object": []}
        for s in self.sessions.values():
            meta = s["meta"]
            if meta.get("purpose") == "object":
                kinds["object"].append(s)
            elif meta.get("purpose") == "train":
                kinds["person" if str(meta.get("walker") or "").strip() else "empty"].append(s)
        keep = []
        for group in kinds.values():
            group.sort(key=lambda s: s["meta"].get("recv_t") or 0)
            keep += group[-TRAIN_KEEP:]
        return sorted(keep, key=lambda s: s["meta"].get("recv_t") or 0)

    def _cmd_train(self, args):
        if self.training or not self.base:
            return
        self._find_sessions()
        sessions = [dict(s) for s in self._newest_recordings()]
        teaching = self._open_train_session()   # a train recording still open: fit from it as far as it has got
        if teaching:
            sessions.append(teaching)
        if not sessions:
            return
        self.lesson.train_cmd(self.now(), teaching and teaching["meta"].get("session"))
        self.training = {"started_t": self.now(), "progress": None,
                         "sessions": sorted(s["meta"]["session"] for s in sessions)}
        base, ver, place = dict(self.base), f"m{self.model_n + 1}", self.place_t
        history, links, zones, crossing = self._baselines(), self.model_links, self.zone_ids, self.crossing
        motion_links, motion_line = self.settings.motion_links, self.presence_line

        def fit():   # may run on another thread: touches nothing of ours
            for s in sessions:   # read back from the bus's files; nothing is kept after the fit
                if s["messages"] is None:
                    s["messages"] = read_session(s["path"], s["meta"].get("recv_t"))
                if not s.get("base"):
                    s["base"] = base_at(history, s["meta"].get("recv_t"))
            return Model(base, ver=ver, links=links, zones=zones, motion_links=motion_links,
                         crossing=crossing, motion_line=motion_line).fit(sessions)

        def done(model):   # back on the loop; model None = the fit failed
            self.training = None
            self.lesson.fitted(self.now(), model is not None)
            if model is None or place != self.place_t:
                return   # the fit failed, or the place changed while it ran: that model is for the old one
            self.model, self.model_n = model, self.model_n + 1
            self._save_model()
            self.decision_ms.clear()
            if self.window:
                self.window["decided"] = False   # the new model decides on the next tick
            self.emit("trained", {"ver": ver, "train_s": model.info()["train_s"]})

        self.spawn(fit, done)

    def _open_train_session(self) -> Optional[dict]:
        """The open recording as a session to fit from, if its purpose is train; else None.
        On the board the bus has it on disk and the fit reads the file as far as it has got."""
        s = self.open_session
        if not s or s["meta"].get("purpose") != "train":
            return None
        if s["messages"] is not None:
            return {"meta": s["meta"], "messages": list(s["messages"])}
        path = self._session_path(s["meta"].get("session"))
        return {"meta": s["meta"], "messages": None, "path": path} if path else None

    def _cmd_relearn(self, args):
        """Forget the current model and train again from this place's recorded sessions."""
        self.model = self.pred = None
        self._cmd_train(args)

    def _cmd_arm(self, args):
        """arm {on: true|false}: "this space should be empty now"."""
        on = args.get("on")
        if isinstance(on, bool) and self.armed.arm(on):
            self._save_armed(on)
            self.emit("armed" if on else "disarmed", {})

    def _save_armed(self, on: bool) -> None:
        """data/sessions/armed.json, so a crash or a redeploy doesn't quietly disarm the space.
        Written through a temporary file; a failed write is logged and never stops the arm."""
        if not self.sessions_dir:
            return
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.sessions_dir / "armed.json.tmp"
            tmp.write_text(json.dumps({"on": on, "t": self.now()}) + "\n", encoding="utf-8")
            os.replace(tmp, self.sessions_dir / "armed.json")
        except OSError as e:
            logging.getLogger("brain").warning("could not save armed.json: %s", e)

    def _load_armed(self) -> None:
        """Arm again after a restart, and say so with a second armed event: the store, the narrator
        and the report see the restart. A missing, cut-off or unreadable file means not armed."""
        if not self.sessions_dir:
            return
        try:
            doc = json.loads((self.sessions_dir / "armed.json").read_text(encoding="utf-8"))
            on = doc["on"] is True
        except (OSError, ValueError, KeyError, TypeError):
            return
        if on and self.armed.arm(True):
            self.emit("armed", {})

    def _cmd_reset_alert(self, args):
        self.watch.reset_alert()
        self._watch_events()

    def _cmd_reset(self, args):
        """Between judges: clear the alert, still timer, check-in, advice and narration."""
        self.watch.reset()
        self._dismissed = self.advice["xy_m"] if self.advice else None
        self.narration = self.advice = None
        self._cmd_arm({"on": False})
        self._watch_events()
        self.emit("reset", {})

    def _cmd_record_start(self, args):
        if not isinstance(args.get("session"), str):
            return   # the bus ignores it too (it has no file name); no recording event for it
        self._keep_open_session()   # back-to-back recordings: the bus closes the old one too
        self.want_session = args.get("session")
        # The bus opens the file and sends back the meta message that opens our copy.
        self.emit("recording", {"on": True, "session": args.get("session")})

    def _cmd_record_stop(self, args):
        session = self._keep_open_session()
        self.want_session = None
        self.emit("recording", {"on": False, "session": session})

    def _keep_open_session(self) -> Optional[str]:
        s, self.open_session = self.open_session, None
        session = s["meta"].get("session") if s else None
        if session and s["keep"]:
            path = self._session_path(session)
            if path is not None:
                self.sessions[session] = {"meta": s["meta"], "messages": None, "path": path}   # the bus has it on disk
            elif s["messages"] is not None:
                self.sessions[session] = {"meta": s["meta"], "messages": s["messages"]}
        return session

    def _session_path(self, session) -> Optional[Path]:
        """The bus's file for a session, if we share its folder and the file is there."""
        if not (self.sessions_dir and session):
            return None
        path = self.sessions_dir / f"{session}.jsonl"
        return path if path.exists() else None

    def _find_sessions(self) -> None:
        """Pick up this place's train and object recordings from the bus's files.

        After a restart (or one in the middle of a recording) nothing here remembers them, but
        the files do. Only recordings whose meta is from this place are taken: a file not
        written since before place_t is skipped without being read.
        """
        if not self.sessions_dir or self.place_t is None:
            return
        for path in sorted(self.sessions_dir.glob("*.jsonl")):
            name = path.stem
            if name in self.sessions or name == self.want_session or "." in name:   # x.states.jsonl, x.events.jsonl
                continue
            try:
                stat = path.stat()
                if stat.st_mtime * 1000 < self.place_t:
                    continue
            except OSError:
                continue
            # A file that was read and isn't a train or object recording of this place (demo
            # recordings pile up all afternoon) is not read again until it changes. This runs on
            # the live loop at every fit, every 15 s during a lesson (#648).
            stamp = (stat.st_mtime_ns, stat.st_size, self.place_t)
            if self._scanned.get(name) == stamp:
                continue
            meta = last_meta(path)
            if meta and meta.get("session") == name and meta.get("purpose") in TRAIN_PURPOSES \
                    and isinstance(meta.get("recv_t"), (int, float)) and meta["recv_t"] >= self.place_t:
                self.sessions[name] = {"meta": meta, "messages": None, "path": path}
                self._scanned.pop(name, None)
            else:
                self._scanned[name] = stamp

    def _save_model(self) -> None:
        """data/sessions/model.pkl, so a restarted brain predicts without a new walk."""
        if not self.sessions_dir:
            return
        try:
            self._write_model()
        except (OSError, pickle.PicklingError) as e:   # a failed write must never hide a trained model
            logging.getLogger("brain").warning("could not save the model: %s", e)

    def _write_model(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.sessions_dir / "model.pkl.tmp"
        with open(tmp, "wb") as f:
            pickle.dump({"ver": self.model.ver, "base": self.model.base, "place_t": self.place_t,
                         "train_sessions": self.model.train_sessions,
                         "train_walkers": self.model.train_walkers,   # None = unknown
                         "model": self.model}, f)
        os.replace(tmp, self.sessions_dir / "model.pkl")   # never a half-written file

    def _load_model(self) -> None:
        """Bring back the last model if it was fit in the place whose baseline we just loaded.

        The automatic baseline after router_home keeps the place, so the model survives it.

        model.pkl is our own file in data/sessions; nothing else is ever unpickled.
        """
        if not (self.sessions_dir and self.base):
            return
        try:
            with open(self.sessions_dir / "model.pkl", "rb") as f:
                doc = pickle.load(f)
            model, ver = doc["model"], str(doc["ver"])
            want = F.feature_names(self.model_links, self.crossing)
            if getattr(model, "features", None) != want or getattr(model, "classes", None) != [0] + self.zone_ids:
                logging.getLogger("brain").warning(
                    "model.pkl was trained on other features or zones (%d features, first %s) than this layout "
                    "has (%d, first %s): not loaded, train again", len(getattr(model, "features", None) or []),
                    (getattr(model, "features", None) or ["?"])[0], len(want), want[0])
                return
            if doc.get("place_t") is not None:
                same_place = doc["place_t"] == self.place_t
            else:
                same_place = doc["base"] == self.base   # a file from before place_t was written
            if not same_place or not model.trained:
                return   # baselined by hand since: the model is for another place
            n = int(ver.lstrip("m"))
        except Exception:
            return       # no file, another scikit-learn, a damaged file: start untrained
        self.model, self.model_n = model, n
        for session in model.train_sessions:   # so train and relearn still find their recordings
            path = self.sessions_dir / f"{session}.jsonl"
            meta = last_meta(path)
            if meta:
                self.sessions[session] = {"meta": meta, "messages": None, "path": path}

    def _cmd_label_mode(self, args):
        mode = args.get("mode")
        if mode not in LABEL_MODES:
            return
        self.label_mode = mode
        if self.mode_file:  # the camera teacher reads its mode from this file
            try:
                with open(self.mode_file, "w", encoding="utf-8") as f:
                    f.write(mode + "\n")
            except OSError as e:   # a bad path must not stop the baseline that asked for "off"
                logging.getLogger("brain").warning("could not write label mode %r to %s: %s", mode, self.mode_file, e)

    def _cmd_router_moved(self, args):
        spot = args.get("spot")
        if not isinstance(spot, str) or spot == HOME or spot not in self.xray.router_spots:
            # state.router can only name a spot from nodes.json, and the x-ray needs its position.
            # Back on S-home is router_home's job (it runs the 3 s check).
            logging.getLogger("brain").warning("router_moved ignored: %r is not a spot to move to", spot)
            return
        self.router = spot
        self._move_router(self.router)
        self._moved_t, self.settle = self.now(), None
        before = self.advice["before_dbm"] if self.advice else self._median(WIFI, self.now() - ADVICE_MEDIAN_MS)
        self.emit("router_moved", {"link": WIFI, "before_dbm": before})   # before_dbm is frozen from here

    def _cmd_router_home(self, args):
        """Section 6: the tray is off and the Pi is back on S-home before this arrives."""
        self.router = HOME
        self._move_router(HOME)
        self.xray.reset()   # what it held was frozen while pred was null; the tray is off by now
        self.advice = self._moved_t = None
        self.settle = self.now() if self.base else None   # pred stays null while the 3 s check runs
        self.emit("router_home", {"link": WIFI})

    def _median(self, link: str, t0: int, t1: Optional[int] = None) -> Optional[float]:
        """Median dBm of a link's readings with t0 <= recv_t < t1 (t1 None = up to now)."""
        vals = [d for t, d in self._recent.get(link, ()) if t >= t0 and (t1 is None or t < t1)]
        return round(statistics.median(vals), 1) if vals else None

    def _check_settle(self, now) -> None:
        """3 s after router_home: every pi5 link within 1 dB of base, or recalibrate."""
        if self.settle is None or now - self.settle < SETTLE_MS:
            return
        start, self.settle = self.settle, None
        for link in self.links:
            if link in self.router_links:   # the router as tx or rx; "pi5b" is another node
                m = self._median(link, start)
                if m is None or abs(m - self.base[link]) > self._settle_db(link):
                    self.recalibrating, self._old_base = True, dict(self.base)
                    self._cmd_label_mode({"mode": "off"})
                    self._start_capture(new_place=False, by_hand=False)
                    self.emit("recalibrating", {"link": link})
                    return

    def _settle_db(self, link: str) -> float:
        """How far a link may sit from its base and still count as back: 1 dB, or
        settings.settle_x_quiet x its own quiet level when that is more."""
        return max(SETTLE_DB, self.settings.settle_x_quiet * self.quiet_db.get(link, 0.0))

    def _line_advice(self, now) -> None:
        """Advice on a layout with a presence line (section 6): the router is cabled and stays put, so the
        advice is about a thing left standing in that line and names no spot to move to.

        It shows while the decision is "object". before_dbm is the line's median over the last 3 s, kept
        current while the thing is there. Once the thing is taken away, after_dbm is the median over 3 s
        starting 2 s later, advice_result carries both, and the advice stays ADVICE_KEEP_MS more.
        Somebody stepping onto the spot takes the advice away at once: a person is never a dead zone."""
        line, adv = self.presence_line, self.advice
        if self.capture or (self.pred and self.pred["present"]):
            self.advice = self._gone_t = self._measured_t = None
            return
        if self._thing:
            self._gone_t = None
            before = self._median(line, now - ADVICE_MEDIAN_MS)
            if before is None or self._dismissed:
                return                               # no reading to show, or cleared by reset while this thing stays
            if adv is not None and adv["after_dbm"] is None:
                adv["before_dbm"] = before           # kept current while the advice shows
                return
            tx, rx = _ends(line)
            names = {n["id"]: n.get("name") or n["id"] for n in self.nodes["nodes"]}
            spots = {n["id"]: n["xyz_m"][:2] for n in self.nodes["nodes"]}
            xy = [round((a + b) / 2, 2) for a, b in zip(spots[tx], spots[rx])]   # the middle of the line
            radio = "Wi-Fi" if line.endswith(":wifi") else "Bluetooth"
            self._measured_t = None
            self.advice = {"id": f"a-{line}-{self._event_n + 1}", "cause": "obstruction", "near": self.xray.nearest_node(xy),
                           "xy_m": xy, "link": line, "to_spot": None, "move_m": [0, 0], "dist_change_m": 0,
                           "text": f"Something is standing in the {radio} line from {names[tx]} to {names[rx]}. "
                                   f"Take it away to get the signal back.",
                           "before_dbm": before, "after_dbm": None, "why": [line]}
            self.emit("advice", {"link": line, "node": self.advice["near"], "before_dbm": before})
            return
        self._dismissed = None
        if adv is None:
            return
        if adv["after_dbm"] is not None:
            if self._measured_t is None or now - self._measured_t >= ADVICE_KEEP_MS:
                self.advice = self._measured_t = None
            return
        if self._gone_t is None:
            self._gone_t = now
        start = self._gone_t + AFTER_START_MS
        if now < start + ADVICE_MEDIAN_MS:
            return
        after, self._gone_t = self._median(line, start, start + ADVICE_MEDIAN_MS), None
        if after is None or line not in self.base or self.base[line] - after >= self.object_db:
            self.advice = None                       # no reading, or the line is still down: nothing was taken away
            return
        adv["after_dbm"], self._measured_t = after, now
        self.emit("advice_result", {"link": line, "before_dbm": adv["before_dbm"], "after_dbm": after})

    def _update_advice(self, now, xray: dict, links: List[dict]) -> None:
        if self.presence_line:
            self._line_advice(now)
            return
        if self.router == HOME:
            adv = advise(xray["xray"], links, self.nodes, xray["objects"]) \
                if xray["xray"] and self.settle is None and not self.capture else None
            before = self._median(WIFI, now - ADVICE_MEDIAN_MS)
            if adv is None or before is None:
                self.advice = self._dismissed = None
                return
            if self._dismissed and _same_object(adv["xy_m"], self._dismissed):
                self.advice = None                # cleared by reset: stays away while that object stays
                return
            self._dismissed = None
            # One object, one advice. The two spots tie for a tray on the centre line and noise
            # would flip the pick (and the sentence on screen) several times a minute, so the
            # first answer stays until the advice goes away or is about another object.
            if self.advice is not None and _same_object(adv["xy_m"], self.advice["xy_m"]):
                self.advice["before_dbm"] = before    # kept current while the advice shows
                return
            adv["before_dbm"] = before
            self.advice = adv
            self.emit("advice", {"link": WIFI, "node": adv["near"], "before_dbm": before})
        elif self.advice and self.advice["after_dbm"] is None and self._moved_t is not None \
                and now >= self._moved_t + AFTER_START_MS + ADVICE_MEDIAN_MS:
            start = self._moved_t + AFTER_START_MS
            after = self._median(WIFI, start, start + ADVICE_MEDIAN_MS)
            if after is not None:
                self.advice["after_dbm"] = after
                self.emit("advice_result", {"link": WIFI, "before_dbm": self.advice["before_dbm"],
                                            "after_dbm": after})

    def _cmd_truth(self, args):
        self.truth = args.get("zone")

    # ---- rules ----

    def _move_router(self, spot):
        try:
            self.xray.set_router(spot)   # the x-ray's geometry follows the router
        except KeyError:
            pass                         # not a spot in nodes.json

    def _set_baseline(self, base: Dict[str, float], expected_hz: Dict[str, float],
                      quiet_db: Optional[Dict[str, float]] = None) -> None:
        self.base, self.expected_hz, self.quiet_db = dict(base), dict(expected_hz), dict(quiet_db or {})
        # The fixed dB numbers give way to a link's own quiet level where a setting says so
        # (brain/settings.py).
        s = self.settings
        self.health.set_quiet(self.quiet_db, s.steady_x_quiet)
        self.watch.checkin_rule.other_db_of = {k: s.checkin_x_quiet * q for k, q in self.quiet_db.items()}
        self.xray.object_min_db = {k: s.object_x_quiet * q for k, q in self.quiet_db.items()}
        if self.presence_line:   # only a thing in the presence line is an object there: no other line can raise one
            self.xray.object_min_db = {k: self.xray.object_min_db.get(k, 0.0) if k == self.presence_line else math.inf
                                       for k in self.links}
        self.windower, self.window = F.Windower(self.base, self.model_links), None
        self._drift_t = self._suspect_t = None
        self._line_present, self._line_seen = False, None
        self._thing, self._thing_since, self._thing_lost, self._moving, self._motion_since = False, None, None, False, None
        self._noted = (self.now(), dict(self.base))
        self.health.set_base(self.base)
        self.health.set_expected(self.expected_hz)
        self.xray.reset()

    def _save_baseline(self, now) -> None:
        """Section 6: data/sessions/baseline.json, for proof/ and for a brain restart.

        A write that fails (a full disk) is logged and nothing more: the baseline is in use
        either way, and baseline_done must still be sent."""
        if not self.sessions_dir:
            return
        try:
            self._write_baseline(now)
        except OSError as e:
            logging.getLogger("brain").warning(
                "could not save the baseline (it is in use, but a restart won't have it): %s", e)

    def _write_baseline(self, now) -> None:
        session = self.open_session["meta"].get("session") if self.open_session else None
        # quiet_db goes into the file only when a setting uses it (they do by default, #734): with the
        # three factors at 0 the file is the older contract's, key for key.
        s = self.settings
        keep_quiet = bool(s.steady_x_quiet or s.checkin_x_quiet or s.settle_x_quiet)
        doc = {"t": now, "session": session,
               "links": {link: {"base_dbm": self.base[link], "expected_hz": self.expected_hz[link],
                                **({"quiet_db": round(self.quiet_db[link], 2)}
                                   if keep_quiet and link in self.quiet_db else {})}
                         for link in self.base}}
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        # place.json: when this place began (the last baseline asked for by hand). proof/ and a
        # restart use recordings from then on only. An automatic baseline leaves it alone.
        # It goes first: a restart that finds the new baseline with the old place would load a
        # model taught somewhere else; the other way round it only starts untrained.
        self._replace("place.json", json.dumps({"t": self.place_t}) + "\n")
        self._replace("baseline.json", json.dumps(doc, indent=1) + "\n")
        # Every baseline is also kept in baselines.jsonl, so a recording can be read against
        # the baseline it was made on, also after a restart.
        with open(self.sessions_dir / "baselines.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now, "base": self.base}) + "\n")

    def _replace(self, name: str, text: str) -> None:
        """Write a file of ours whole or not at all: a temporary file, flushed to the disk, then
        renamed over the old one (as model.pkl is). Power pulled mid-write leaves the old file."""
        tmp = self.sessions_dir / f"{name}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.sessions_dir / name)
        except OSError:
            try:
                tmp.unlink()        # a failed write (a full disk) leaves no half file behind
            except OSError:
                pass
            raise

    def _baselines(self) -> List[dict]:
        """Every baseline taken so far, oldest first: [{"t", "base"}] (baselines.jsonl, or just
        the ones this run has seen when there is no sessions folder)."""
        if not self.sessions_dir:
            return list(self._base_log)
        out = []
        try:
            with open(self.sessions_dir / "baselines.jsonl", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        out.append({"t": entry["t"], "base": {k: float(v) for k, v in entry["base"].items()}})
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
        except OSError:
            pass
        return sorted(out, key=lambda e: e["t"])

    def _load_baseline(self) -> None:
        if not self.sessions_dir:
            return
        try:
            doc = json.loads((self.sessions_dir / "baseline.json").read_text(encoding="utf-8"))
            links = doc["links"]
            base = {k: float(v["base_dbm"]) for k, v in links.items() if k in self.links}
            expected = {k: float(v["expected_hz"]) for k, v in links.items() if k in self.links}
            quiet = {k: float(v["quiet_db"]) for k, v in links.items()
                     if k in self.links and isinstance(v.get("quiet_db"), (int, float))}   # a file from before has none
        except (OSError, ValueError, KeyError, TypeError):
            return   # no file, or not one of ours: start without a baseline
        if base:
            self._set_baseline(base, expected, quiet)
            self.place_t = self._read_place(doc.get("t"))

    def _read_place(self, baseline_t) -> Optional[int]:
        """place.json's time; without that file, the baseline's own time."""
        try:
            t = json.loads((self.sessions_dir / "place.json").read_text(encoding="utf-8"))["t"]
        except (OSError, ValueError, KeyError, TypeError):
            t = baseline_t
        return int(t) if isinstance(t, (int, float)) else None

    def _watch_events(self):
        for kind, info in self.watch.pop_events():
            self.emit(kind, info)

    def _start_capture(self, new_place: Optional[bool] = None, by_hand: Optional[bool] = None):
        """new_place None = keep what the running capture was asked for (a restart of its 20 s).
        by_hand = asked for with the baseline cmd (with or without keep_model), not the automatic one."""
        if by_hand is None:
            by_hand = bool(self.capture and self.capture.get("by_hand"))
        asked = self.capture["asked"] if self.capture else None   # set on the first tick: the clock may not have started
        if new_place is None:
            new_place = bool(self.capture and self.capture["new_place"])
        # clean_ms: capture time so far with every condition holding. paused: since when a passer-by
        # has been in the camera's view. last: the previous clean tick.
        self.capture = {"start": None, "messages": [], "new_place": new_place, "asked": asked,
                        "by_hand": by_hand, "clean_ms": 0, "paused": None, "last": None}

    def _new_place(self, now) -> None:
        """The operator's baseline finished: nothing learned before it is used from here on.

        The model goes (pred is null until the next train) and so do the recordings held for
        training; a recording still open carries on, it belongs to this place. Files stay on disk.
        """
        self.place_t = now
        self.model = self.pred = self._raw = self.raw_kind = None
        self.sessions = {}
        self.decision_ms.clear()

    def _capture_ok(self, now) -> bool:
        """Section 6: health ok, the camera on and seeing nobody, label_mode off, every link reporting.

        The automatic baseline after router_home also runs with the camera unplugged (the demo
        unplugs it before the router moves); with the camera on it must still see nobody.
        """
        return self._capture_wait(now) is None

    def _capture_wait(self, now) -> Optional[str]:
        """What the baseline is waiting for, in words for the log; None when every condition holds."""
        lb = self.label
        cam_on = bool(self.cam and self.cam[1] == "on" and now - self.cam[0] <= CAM_SILENT_MS)
        if not cam_on:
            pass   # no camera to ask (unplugged at the judging desk): the operator keeps the area empty
        elif lb is None or now - lb["recv_t"] > TEACHER_FRESH_MS:
            return "no camera labels in the last second"
        elif (lb.get("persons_in_frame") or 0) != 0:
            return "the camera sees somebody"
        if self.label_mode != "off":
            return f"label mode is {self.label_mode}, not off"
        # Measured on the kit (#634): Bluetooth links give 7 to 13 readings a second, one of them 1.7,
        # and unevenly. A link that slow goes a full second without a reading every few seconds, and
        # reads "stale" by chance, so 1 s of silence or any not-ok health restarted the 20 s for ever.
        # Every kind of baseline now waits only for a link silent for 3 s (the blind rule's and
        # tamper's silence) or for health blind.
        quiet = [link for link in self.model_links if now - self._last_seen.get(link, -10**15) > SILENT_MS]
        if quiet:
            return f"no readings in the last {SILENT_MS // 1000} s from " + ", ".join(quiet)
        if self.health.blind:
            return "link health is blind"
        return None

    def _passer_pause(self, now, wait) -> bool:
        """True while a running capture is only held up by somebody in the camera's view who is not
        in the layout (present false): a passer-by in the aisle. Their readings are left out and the
        20 s carry on afterwards. Somebody inside the layout, or in view for over PASSER_PAUSE_MS,
        starts the 20 s again, as does any other broken condition."""
        c = self.capture
        if c["start"] is None or wait != "the camera sees somebody" or (self.label or {}).get("present"):
            return False
        if c["paused"] is None:
            c["paused"], c["last"] = now, None
        return now - c["paused"] <= PASSER_PAUSE_MS

    def _capture_clean_ms(self, now) -> int:
        """Capture time so far, not counting the pauses."""
        c = self.capture
        if c["last"] is not None:
            c["clean_ms"] += now - c["last"]
        c["paused"], c["last"] = None, now
        return c["clean_ms"]

    def _tick(self):
        now = self.now()
        if self.capture:
            wait = self._capture_wait(now)
            if self.capture["asked"] is None and now > 0:
                # On the feed clock time is 0 until the first reading. A state tick before it must
                # not start the 120 s there, or the first reading (epoch ms) gives up at once (#598).
                self.capture["asked"] = now
            if wait != self._wait_said:             # said once per reason, not on every message
                self._wait_said = wait
                log = logging.getLogger("brain")
                log.warning("baseline is waiting: %s", wait) if wait else log.info("baseline: capturing 20 s")
            if (wait and self.capture["by_hand"] and self.capture["asked"] is not None
                    and now - self.capture["asked"] >= BASELINE_GIVE_UP_MS):
                # Pressed by mistake in front of an audience, or the room never cleared: without
                # this pred stays hidden for ever. The old baseline and the model are untouched.
                logging.getLogger("brain").warning(
                    "baseline given up after %d s (%s); press Baseline again when the square is clear",
                    BASELINE_GIVE_UP_MS // 1000, wait)
                self.capture, self._wait_said = None, ()
            elif wait and self._passer_pause(now, wait):
                pass                                # somebody walks past the camera: hold, don't start again
            elif wait:
                self._start_capture()               # a condition broke: the 20 s start again
            elif self.capture["start"] is None:
                self.capture["start"] = self.capture["last"] = now
            elif self._capture_clean_ms(now) >= BASELINE_MS:
                msgs, new_place, self.capture = self.capture["messages"], self.capture["new_place"], None
                self._wait_said = ()
                expected = {link: round(sum(1 for m in msgs if m["link"] == link) / (BASELINE_MS / 1000), 1)
                            for link in self.links}
                self._set_baseline(F.baseline(msgs), expected, F.quiet(msgs))
                self._base_log.append({"t": now, "base": dict(self.base)})
                if new_place or self.place_t is None:
                    self._new_place(now)
                self._save_baseline(now)
                self.emit("baseline_done", {})
                if self.recalibrating:   # how far did the room move from the old baseline?
                    self.recalibrating = False
                    moved = {link: abs(self.base[link] - old) for link, old in self._old_base.items()
                             if link in self.base}
                    over = {link: by - self._settle_db(link) for link, by in moved.items()}   # past its own limit
                    worst = max(over, key=over.get, default=None)
                    if worst and over[worst] > 0:
                        self.emit("drift", {"link": worst})   # the screen offers relearn
        self._check_settle(now)
        self._decide(now)

    def _decide(self, now):
        # A layout with a presence line needs no model and no lesson: the line decides by itself (_line_pred).
        if not ((self.model or self.presence_line) and self.window):
            self.pred = self.raw_kind = None
            self.watch.on_pred(now, None)
            return
        if not self.window.get("decided"):   # the classifier runs on every new window
            t0 = time.perf_counter()
            thing = self._thing_says()
            # present is passed only on a layout with a presence line: everywhere else the call is the one
            # it always was, for anything that stands in for the model (proof's replay does).
            line = {"present": False if thing else self._line_says()} if self.presence_line else {}
            self._raw = self.model.predict(self.window, hold=self._still_down(), **line) if self.model                 else self._line_pred(line["present"])
            if thing:
                self._raw["kind"] = "object"   # down and steady with no body in it: never a person, never nobody
                self._raw["why"] = [self.presence_line]
            elif self.presence_line and self._raw["present"]:
                self._raw["motion"] = self._motion_says()
            if self.presence_line and not self._raw["present"]:
                self._moving, self._motion_since, self._here_t = False, None, None   # whoever steps on next starts as still
            elif self.presence_line and line["present"] is False and self._raw["kind"] == "object":
                self._raw["kind"] = "none"     # the line is clear: no other line can say "object" on this layout
            self.decision_ms.append((time.perf_counter() - t0) * 1000)
            self.window["decided"] = True
            self.raw_kind = self._raw["kind"]   # health wants this even while pred is hidden
            self._fresh = True
        if self.capture or self.router != HOME or self.health.blind or self.settle is not None:
            self.pred = None                 # hidden; SENSOR BLIND never reads as "empty"
            self.watch.on_pred(now, None)    # the alert timer pauses, the LED shows "?"
            self.armed.on_pred(None)         # and nothing is raised on a decision nobody may see
            return
        if not self._fresh:
            return
        unheard = [] if self._raw["present"] else self._unheard(now)
        if unheard:
            # "Nobody" from a window in which a link the sensor needs has no reading says nothing:
            # a link with no readings counts as sitting on its baseline, which is what an empty
            # area looks like (#650). A decision that somebody is there still goes out.
            if self._gone(now, unheard) and self.pred is not None:
                self.pred = None                 # unknown, as for blind, until the link is back
                self.watch.on_pred(now, None)
                self.armed.on_pred(None)
            return                               # otherwise the last decision stands (under 2 s)
        self._fresh = False
        pred = dict(self._raw)
        self.watch.on_pred(self.window["end"], pred)
        if self.sense:                           # the check-in on this layout: leaning out of the lines
            quiet = [self.quiet_db[k] for k in self.sense if k in self.quiet_db]
            self.watch.on_crossing(self.window["end"], F.crossing_drop(self.window, self.sense),
                                   sum(quiet) / len(quiet) if quiet else 0.0, self.sense[0])
        pred["still_s"] = round(self.watch.still_ms / 1000, 1)
        self.pred = pred
        self._follow_drift(self.window["end"], pred)
        self.lesson.saw(now, pred, self.label)
        self._announce(pred["zone"] if pred["present"] else 0)
        intruder = self.armed.on_pred(pred)
        if intruder is not None:
            self.emit("intrusion", {"zone": intruder})
        for zone in self.armed.pop_passed():   # appeared while armed and gone before the hold was over
            self.emit("passed_by", {"zone": zone})

    def _follow_drift(self, now, pred) -> None:
        """The empty level of the lines that cross the spot follows slow drift (settings.drift_follow_s).

        On the kit the empty level of the one good line moved 5 dB in five minutes, more than the
        weakest person takes off it. So while the decision is "nobody", each crossing line's
        baseline moves towards its median in this window with a time constant of drift_follow_s:
        at 30 s a drift of 1 dB a minute is followed half a dB behind, and a person stepping in
        over a second moves it by a tenth of a dB before it stops. It stops (the level is frozen)
        the moment the lines are SUSPECT_DB down, or settings.suspect_x_quiet x their quiet level,
        which is well before the model says "present", and stays stopped for as long as somebody
        is there: a person standing still for three minutes, or thirty, is never taken for the
        empty spot. The one way back: the model has said "nobody" all through a dip of
        UNSTICK_MS, so the dip is the room (a chair moved), not a person.
        Only the crossing lines: the desk's own lines keep the captured baseline, since a tray
        left on them is what the dead-zone advice measures. A layout that marks no crossing
        lines keeps the fixed baseline it always had. On a layout with a presence line only that
        line is read and only its level follows: the other lines keep the captured baseline."""
        tau_ms = self.settings.drift_follow_s * 1000
        if not (self.sense and tau_ms and self.windower):
            return
        last, self._drift_t = self._drift_t, now
        if pred["present"] or last is None:
            self._suspect_t = None
            return
        if self._thing:
            return   # a thing in the presence line: its empty level stays, so the gain shows when the thing goes
        drop = F.crossing_drop(self.window, self.sense)
        quiet = [self.quiet_db[k] for k in self.sense if k in self.quiet_db]
        floor = max(SUSPECT_DB, self.settings.suspect_x_quiet * (sum(quiet) / len(quiet) if quiet else 0.0))
        if drop is None:
            return
        # The presence line on its own, too: a thing in it may take 3 dB off that line and nothing off the others.
        own = self.window["links"].get(self.presence_line) or {} if self.presence_line else {}
        line_down = bool(own.get("n")) and self.window["base"][self.presence_line] - own["median"] >= SUSPECT_DB
        if drop >= floor or line_down:
            self._suspect_t = now if self._suspect_t is None else self._suspect_t
            if now - self._suspect_t < UNSTICK_MS:
                return
        else:
            self._suspect_t = None
        share = 1.0 - math.exp(-min(now - last, 1000) / tau_ms)
        for link in self.sense:
            stats = self.window["links"].get(link) or {}
            if stats.get("n") and link in self.base:
                self.base[link] += (stats["median"] - self.base[link]) * share
                self.windower.base[link] = self.base[link]
        self.health.set_base({k: self.base[k] for k in self.sense if k in self.base})
        noted_t, noted = self._noted
        if now - noted_t >= DRIFT_NOTE_MS and any(abs(self.base[k] - noted.get(k, self.base[k] + 99)) >= DRIFT_NOTE_DB
                                                  for k in self.sense if k in self.base):
            # A recording is read against the level in force when it was made (train), so the
            # followed level is kept with the baselines: in memory, and in baselines.jsonl.
            self._noted = (now, dict(self.base))
            self._base_log.append({"t": now, "base": dict(self.base)})
            if self.sessions_dir:
                try:
                    with open(self.sessions_dir / "baselines.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": now, "base": self.base}) + "\n")
                except OSError:
                    pass   # the level is still followed; only a later fit reads it less exactly

    def _line_pred(self, present: Optional[bool]) -> dict:
        """The decision on a layout with a presence line when no model has been trained (no lesson was ever
        run, or a baseline dropped the model): the line's word alone. Somebody there is a person in the
        layout's zone (the one spot), and probs says the same, 0 or 1: there is no model to weigh anything.
        The caller adds what it adds to a model's answer: "object" for a thing left in the line, and moving
        or still from the line's spread."""
        here, zone = bool(present), self.zone_ids[0]
        return {"present": here, "kind": "person" if here else "none", "zone": zone if here else 0,
                "zone_set": [zone] if here else [],
                "probs": [0.0 if here else 1.0, 1.0 if here else 0.0] + [0.0] * (len(self.zone_ids) - 1),
                "motion": None, "still_s": None, "why": [self.presence_line] if here else []}

    def _line_says(self) -> Optional[bool]:
        """What the layout's presence line says about this window: True somebody, False nobody, None when
        the layout names no such line (then the model decides, as on every other layout)."""
        if not self.presence_line:
            return None
        end = self.window["end"]

        def drop(link):
            stats, base = self.window["links"].get(link) or {}, self.window["base"].get(link)
            return base - stats["median"] if stats.get("n") and base is not None else None

        down = drop(self.presence_line)
        if down is not None:
            self._line_seen = end
            self._line_present = down >= (self.presence_off_db if self._line_present else self.presence_on_db)
        elif self._line_present:
            # The line is silent (Pi B's readings come over the hotspot). Its last word stands for
            # second_hold_s; by then health is blind and no decision is shown. No other line has a say.
            if not (self._line_seen is not None and end - self._line_seen <= self.presence_hold_ms):
                self._line_present = False
        return self._line_present

    def _thing_says(self) -> bool:
        """True while the presence line says a thing has been left standing in it (section 6): over the
        last 2 s its median sits object_db or more under the empty level, and less than a person takes
        (object_max_db), and its spread is no more than the empty line's own (object_spread_db): a steady
        drop with no body wobbling in it. That has to hold for object_hold_s, and ends THING_GRACE_MS after
        it stops. A person is deeper or wobbles, so a person on the spot is never a thing, however still."""
        if not self.presence_line:
            return False
        end = self.window["end"]
        long = (self.window.get("long") or {}).get(self.presence_line) or {}
        base = self.window["base"].get(self.presence_line)
        looks = False
        if long.get("median") is not None and base is not None:
            looks = (self.object_db <= base - long["median"] < self.object_max_db
                     and long["std"] <= self.object_spread_db)
        if looks:
            self._thing_lost = None
            self._thing_since = end if self._thing_since is None else self._thing_since
            if not self._thing and end - self._thing_since >= self.object_hold_ms:
                self._thing, self._line_present = True, False   # whoever put it there has to arrive again to be somebody
        elif self._thing:
            self._thing_lost = end if self._thing_lost is None else self._thing_lost
            if end - self._thing_lost >= THING_GRACE_MS:
                self._thing, self._thing_since, self._thing_lost = False, None, None
        else:
            self._thing_since = None
        return self._thing

    def _spread_now(self) -> Optional[float]:
        """The presence line's spread: the std of its readings over the last 2 s, and never over readings
        from before the line said somebody is there, so stepping on (15 dB in a third of a second) is
        not itself read as moving about. None under LONG_MIN readings."""
        end = self.window["end"]
        self._here_t = end if self._here_t is None else self._here_t
        if self._here_t <= end - SPREAD_MS:
            return ((self.window.get("long") or {}).get(self.presence_line) or {}).get("std")
        dbms = self.windower.trail(self.presence_line, self._here_t, end) if self.windower else []
        if len(dbms) < F.LONG_MIN:
            return None
        mean = sum(dbms) / len(dbms)
        return math.sqrt(sum((d - mean) ** 2 for d in dbms) / len(dbms))

    def _motion_says(self) -> str:
        """moving | still for somebody on the spot, from the presence line's spread over the last 2 s
        (section 6). The line arrives 25 times a second and sits within 1 dB when the spot is empty, so
        its spread is the body moving; the Bluetooth lines wobble 2 to 5 dB by themselves and have no
        say. The word is steady: moving only once the spread has been at the boundary or over it for
        motion_hold_s without a break, still again only once it has been under the lower boundary
        (still_spread_db) for as long. Between the two the word stands. So the sway of a person standing
        still never flips it, and somebody who starts stepping about reads as moving motion_hold_s later.
        The boundary is the one the lesson's labels gave the model, else the layout file's
        (moving_spread_db); the lower one keeps its share of it."""
        std = self._spread_now()
        if std is not None:
            end = self.window["end"]
            edge = getattr(self.model, "spread_split", None) or self.moving_spread_db
            other = std < edge * self.still_share if self._moving else std >= edge
            if not other:
                self._motion_since = None
            else:
                self._motion_since = end if self._motion_since is None else self._motion_since
                if end - self._motion_since >= self.motion_hold_ms:
                    self._moving, self._motion_since = not self._moving, None
        return "moving" if self._moving else "still"

    def _still_down(self) -> bool:
        """True when the last decision sent said somebody is there and the lines that cross the
        spot still sit under their baselines: their median drops in this window, averaged, are
        at least STAY_DB, or settings.stay_x_quiet x their quiet level where that is more. The
        model, taught by the camera, decides when somebody has arrived; this keeps a person who is
        standing there from blinking out for a window. Only on a layout that marks those lines."""
        if self.presence_line or not (self.crossing and self.pred and self.pred["present"]):
            return False   # with a presence line, that line's own on and off levels are the hold
        drop = F.crossing_drop(self.window, self.crossing)
        quiet = [self.quiet_db[k] for k in self.crossing if k in self.quiet_db]
        floor = max(STAY_DB, self.settings.stay_x_quiet * (sum(quiet) / len(quiet) if quiet else 0.0))
        return drop is not None and drop >= floor

    def _unheard(self, now) -> List[str]:
        """The links that can blind the sensor and have no reading in the last window (1 s),
        though the baseline heard them."""
        return [k for k in self.health.classifier_links
                if self.expected_hz.get(k) and now - self._last_seen.get(k, -10**15) > F.WINDOW_MS]

    def _gone(self, now, unheard) -> bool:
        """True when one of them is stale as well, and has been silent for longer than chance
        allows at its own rate: GONE_READINGS readings' worth, and never under the 1 s window.
        (A healthy link at 5 or 6 readings a second has a 1 s gap about once a minute, and a
        2 s stretch with too few readings about as often; neither may blink "unknown".)"""
        # On a layout with a presence line that line's last word stands for second_hold_s while it has no
        # readings (section 6): a pause of a second or two never blanks the decision. If the line stays silent
        # the sensor goes blind before the hold is over, and that hides the decision.
        floor = max(F.WINDOW_MS, self.presence_hold_ms) if self.presence_line else F.WINDOW_MS
        return any(k in self._quiet
                   and now - self._last_seen[k] > max(floor, GONE_READINGS * 1000 / self.expected_hz[k])
                   for k in unheard)

    def _announce(self, zone: int) -> None:
        """enter, exit and zone_change, once the new zone has held for settings.zone_hold decisions.

        One flickering decision is not somebody walking in. Hidden spans (pred null) are skipped:
        whatever holds once pred is back gets announced then.
        """
        if zone == self._said_zone:
            self._next_zone = (zone, 0)
            return
        n = self._next_zone[1] + 1 if self._next_zone[0] == zone else 1
        self._next_zone = (zone, n)
        if n < self.settings.zone_hold:
            return
        if self._said_zone == 0:
            self.emit("enter", {"zone": zone})
        elif zone == 0:
            self.emit("exit", {"zone": self._said_zone})   # the zone they left from
        else:
            self.emit("zone_change", {"zone": zone})
        self._said_zone = zone

    def emit(self, kind: str, info: dict) -> None:
        # event.json allows only these keys in info, and no nulls.
        info = {k: info[k] for k in EVENT_INFO if info.get(k) is not None}
        self._seq += 1
        self._event_n += 1
        self.events.append({"v": 2, "type": "event", "t": self.now(), "seq": self._seq, "src": self.src,
                            "id": f"e{self._event_n}", "kind": kind, "info": info})

    def pop_events(self) -> List[dict]:
        out, self.events = self.events, []
        return out

    # ---- output ----

    def _link_row(self, row: dict, weights: Dict[str, float]) -> dict:
        """A listed link's dbm stays a number: a link quiet for over 1 s keeps its last value
        (and the drop that goes with it); rate_hz and status are what show it is stale."""
        link = row["id"]
        if row["dbm"] is None:
            dbm, base = self._last_dbm[link], self.base.get(link)
            row = dict(row, dbm=round(dbm, 1), drop_db=None if base is None else round(base - dbm, 1))
        else:
            self._last_dbm[link] = row["dbm"]
        return dict(row, why=weights.get(link, 0.0))

    def _why_weights(self) -> Dict[str, float]:
        """0-1 per link: how much it explains the current decision."""
        if not (self.model and self.window and self.pred):
            return {}
        raw = {}
        for i, link in enumerate(self.model_links):
            drop = (self.window["links"].get(link) or {}).get("drop_db") or 0.0
            raw[link] = float(self.model._link_weight[i]) * abs(drop)
        top = max(raw.values()) or 1.0
        return {link: round(v / top, 2) for link, v in raw.items()}

    def state(self) -> dict:
        now = self.now()
        self._tick()
        # A baseline asked for by hand, with or without keep_model, measures the rates again; the
        # old ones don't judge it. (The same layout at another desk can have a slower link: judged
        # against its old rate it went stale, then blind, and blind held up the very capture that
        # would have measured the new rate.)
        health = self.health.update(now, self.raw_kind, self.router == HOME, self.capture is not None,
                                    rates_known=not (self.capture and self.capture["by_hand"]))
        self._health_ok = health["health"]["status"] == "ok"
        self._quiet = [row["id"] for row in health["links"]
                       if row["status"] != "ok" and row["id"] in self.health.classifier_links]
        if self.pred is not None and not self.pred["present"] and self._gone(now, self._unheard(now)):
            self.pred = None                     # a link the sensor needs has gone quiet: not "nobody"
            self.watch.on_pred(now, None)
            self.armed.on_pred(None)
        if self.health.blind and self.pred is not None:
            self.pred = None
            self.watch.on_pred(now, None)
            self.armed.on_pred(None)
        # Section 5: xray is null before the first baseline, links are [] before any reading.
        xray = self.xray.update(now, self.pred["kind"] if self.pred else None) if self.base else \
            {"xray": None, "objects": [], "events": []}
        for e in health["events"] + xray["events"]:
            self.emit(e["kind"], e["info"])
        for kind, info in self.tamper.update(now, self.armed.on, self._last_seen, self._hall_seen):
            self.emit(kind, info)   # judged whatever health says: blind is exactly when it matters
        self._watch_events()
        weights = self._why_weights()
        links = [self._link_row(row, weights) for row in health["links"]
                 if row["id"] in self._heard]   # a link is listed once it has a reading
        self._update_advice(now, xray, [row for row in links if row["id"] in self.model_links])
        cam = self.cam[1] if self.cam and now - self.cam[0] <= CAM_SILENT_MS else "off"
        if cam != self._said_cam and cam in ("on", "off", "stalled"):
            self._said_cam = cam
            self.emit(f"cam_{cam}", {})
        teaching = self._open_train_session()
        if self.lesson.due(now, teaching and teaching["meta"].get("session"), cam, self.training is not None):
            self._cmd_train({})   # the lesson's next fit, or its last one
        self._seq += 1
        lb = self.label
        teacher = None
        if cam == "on" and lb and now - lb["recv_t"] <= TEACHER_FRESH_MS and not lb.get("clipped"):
            teacher = {"present": bool(lb.get("present")), "zone": lb.get("zone") or 0, "motion": lb.get("motion")}
        model = self.model.info() if self.model else {"trained": False, "ver": None, "train_s": None,
                                                      "windows": 0, "train_sessions": []}
        model["ms_per_decision"] = round(statistics.median(self.decision_ms), 2) if self.decision_ms else None
        model["training"] = self.lesson.block(self.training)
        state = {"v": 2, "type": "state", "t": now, "seq": self._seq, "src": self.src,
                 "cam": cam, "router": self.router, "links": links,
                 "health": health["health"],
                 "pred": self.pred, "objects": xray["objects"], "xray": xray["xray"],
                 "alert": self.watch.alert_block(), "checkin": self.watch.checkin, "advice": self.advice and dict(self.advice), "narration": self.narration, "teacher": teacher,
                 "model": model, "board": self.board_stats()}
        if self.tamper.silent:
            state["tamper"] = list(self.tamper.silent)   # only while a node is listed (absent = none)
        if self.armed.on:
            # Section 5: a missing "armed" means false. Sent only while armed until state.json
            # knows the field (#440); a state that never arms is byte for byte what it was.
            state["armed"] = True
        if self.chain and time.monotonic() - self.chain[0] <= CHAIN_FRESH_S:
            state["chain"] = dict(self.chain[1])   # optional: absent when no head was heard lately
        return self.hall.add_to(state, now)
