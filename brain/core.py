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
from brain.health import Health
from brain.lesson import Lesson
from brain.train import Model
from brain.xray import Xray

BASELINE_MS = 20_000
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
EVENT_INFO = ("zone", "link", "node", "before_dbm", "after_dbm", "on", "session")   # contracts/schemas/event.json
SILENT_MS = 3_000        # a keep-model baseline restarts only for a link with no reading for this long
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
        self.health = Health.from_nodes(nodes, classifier_links=[k for k in links if k not in over_hotspot])
        self.xray = Xray.from_nodes(nodes)
        self.watch = Watch({z["id"]: z.get("still_alert_s") for z in nodes["zones"]}, led, self.settings)
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
        self.nodes = nodes
        self._recent: Dict[str, deque] = {link: deque() for link in links}   # (recv_t, dbm), last 10 s
        self.advice: Optional[dict] = None
        self._dismissed: Optional[list] = None    # xy_m of an advice that reset cleared
        self._moved_t: Optional[int] = None       # when router_moved came
        self.settle: Optional[int] = None         # when router_home came, while its 3 s check runs
        self.recalibrating = False                # the automatic baseline after a failed check
        self._old_base: Dict[str, float] = {}
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
        self.events: List[dict] = []
        self._seq = 0       # one counter for everything we send to the screens (section 4)
        self._cmd_seq = 0   # and one for the commands we pass to the bus, a separate socket
        self._event_n = 0
        self._load_baseline()
        self._load_model()
        self._load_armed()

    def now(self) -> int:
        return self._clock() if self._clock else self.feed_t

    # ---- inputs ----

    def on_message(self, msg: dict) -> None:
        """One message forwarded by the bus (it carries recv_t)."""
        t, kind = msg.get("recv_t"), msg.get("type")
        if t is None:
            return
        if kind == "rssi" and not (_is_reading(msg.get("dbm")) and isinstance(msg.get("link"), str)):
            return   # no number, NaN (JSON lets it through) or a link that isn't a name: never used
        if kind == "label" and not _is_label(msg):
            return   # a zone or a count that isn't a number: the windows would choke on it
        self.feed_t = max(self.feed_t, int(t))
        if kind == "rssi" and self._hall_nodes and isinstance(msg.get("link"), str):
            tx = _ends(msg["link"])[0]
            if tx in self._hall_nodes and msg["link"] not in self.links:
                self._hall_seen.setdefault(tx, {})[msg["link"]] = int(t)
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
                if self.capture and self.capture["start"] is not None:
                    self.capture["messages"].append(msg)
            if self.windower:
                for window in self.windower.push(msg):
                    self.window = window
        self._tick()

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

    def _cmd_train(self, args):
        if self.training or not self.base:
            return
        self._find_sessions()
        sessions = [dict(s) for s in self.sessions.values() if s["meta"].get("purpose") in TRAIN_PURPOSES]
        teaching = self._open_train_session()   # a train recording still open: fit from it as far as it has got
        if teaching:
            sessions.append(teaching)
        if not sessions:
            return
        self.lesson.train_cmd(self.now(), teaching and teaching["meta"].get("session"))
        self.training = {"started_t": self.now(), "progress": None,
                         "sessions": sorted(s["meta"]["session"] for s in sessions)}
        base, ver, place = dict(self.base), f"m{self.model_n + 1}", self.place_t
        history, links, zones = self._baselines(), self.links, self.zone_ids
        motion_links = self.settings.motion_links

        def fit():   # may run on another thread: touches nothing of ours
            for s in sessions:   # read back from the bus's files; nothing is kept after the fit
                if s["messages"] is None:
                    s["messages"] = read_session(s["path"], s["meta"].get("recv_t"))
                if not s.get("base"):
                    s["base"] = base_at(history, s["meta"].get("recv_t"))
            return Model(base, ver=ver, links=links, zones=zones, motion_links=motion_links).fit(sessions)

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
                if path.stat().st_mtime * 1000 < self.place_t:
                    continue
            except OSError:
                continue
            meta = last_meta(path)
            if meta and meta.get("session") == name and meta.get("purpose") in TRAIN_PURPOSES \
                    and isinstance(meta.get("recv_t"), (int, float)) and meta["recv_t"] >= self.place_t:
                self.sessions[name] = {"meta": meta, "messages": None, "path": path}

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
            want = F.feature_names(self.links)
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
                if m is None or abs(m - self.base[link]) > SETTLE_DB:
                    self.recalibrating, self._old_base = True, dict(self.base)
                    self._cmd_label_mode({"mode": "off"})
                    self._start_capture(new_place=False, by_hand=False)
                    self.emit("recalibrating", {"link": link})
                    return

    def _update_advice(self, now, xray: dict, links: List[dict]) -> None:
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

    def _set_baseline(self, base: Dict[str, float], expected_hz: Dict[str, float]) -> None:
        self.base, self.expected_hz = dict(base), dict(expected_hz)
        self.windower, self.window = F.Windower(self.base, self.links), None
        self.health.set_base(self.base)
        self.health.set_expected(self.expected_hz)
        self.xray.reset()

    def _save_baseline(self, now) -> None:
        """Section 6: data/sessions/baseline.json, for proof/ and for a brain restart."""
        if not self.sessions_dir:
            return
        session = self.open_session["meta"].get("session") if self.open_session else None
        doc = {"t": now, "session": session,
               "links": {link: {"base_dbm": self.base[link], "expected_hz": self.expected_hz[link]}
                         for link in self.base}}
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "baseline.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        # Every baseline is also kept in baselines.jsonl, so a recording can be read against
        # the baseline it was made on, also after a restart.
        with open(self.sessions_dir / "baselines.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now, "base": self.base}) + "\n")
        # place.json: when this place began (the last baseline asked for by hand). proof/ and a
        # restart use recordings from then on only. An automatic baseline leaves it alone.
        (self.sessions_dir / "place.json").write_text(json.dumps({"t": self.place_t}) + "\n", encoding="utf-8")

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
        except (OSError, ValueError, KeyError, TypeError):
            return   # no file, or not one of ours: start without a baseline
        if base:
            self._set_baseline(base, expected)
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
        self.capture = {"start": None, "messages": [], "new_place": new_place, "asked": asked,
                        "by_hand": by_hand}

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
        # baseline {keep_model: true} is the same layout set down at a new desk, in a hall full of
        # phones: only a link silent for 3 s, or health blind, holds it up. A stale link does not.
        lenient = bool(self.capture and self.capture["by_hand"] and not self.capture["new_place"])
        gap = SILENT_MS if lenient else LINK_FRESH_MS
        quiet = [link for link in self.links if now - self._last_seen.get(link, -10**15) > gap]
        if quiet:
            return f"no readings in the last {gap // 1000} s from " + ", ".join(quiet) if lenient else \
                "no readings in the last second from " + ", ".join(quiet)
        if self.health.blind or (not self._health_ok and not lenient):
            return "link health is blind" if lenient else "link health is not ok"
        return None

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
            elif wait:
                self._start_capture()               # a condition broke: the 20 s start again
            elif self.capture["start"] is None:
                self.capture["start"] = now
            elif now - self.capture["start"] >= BASELINE_MS:
                msgs, new_place, self.capture = self.capture["messages"], self.capture["new_place"], None
                self._wait_said = ()
                expected = {link: round(sum(1 for m in msgs if m["link"] == link) / (BASELINE_MS / 1000), 1)
                            for link in self.links}
                self._set_baseline(F.baseline(msgs), expected)
                self._base_log.append({"t": now, "base": dict(self.base)})
                if new_place or self.place_t is None:
                    self._new_place(now)
                self._save_baseline(now)
                self.emit("baseline_done", {})
                if self.recalibrating:   # how far did the room move from the old baseline?
                    self.recalibrating = False
                    moved = {link: abs(self.base[link] - old) for link, old in self._old_base.items()
                             if link in self.base}
                    worst = max(moved, key=moved.get, default=None)
                    if worst and moved[worst] > SETTLE_DB:
                        self.emit("drift", {"link": worst})   # the screen offers relearn
        self._check_settle(now)
        self._decide(now)

    def _decide(self, now):
        if not (self.model and self.window):
            self.pred = self.raw_kind = None
            self.watch.on_pred(now, None)
            return
        if not self.window.get("decided"):   # the classifier runs on every new window
            t0 = time.perf_counter()
            self._raw = self.model.predict(self.window)
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
        self._fresh = False
        pred = dict(self._raw)
        self.watch.on_pred(self.window["end"], pred)
        pred["still_s"] = round(self.watch.still_ms / 1000, 1)
        self.pred = pred
        self.lesson.saw(now, pred, self.label)
        self._announce(pred["zone"] if pred["present"] else 0)
        intruder = self.armed.on_pred(pred)
        if intruder is not None:
            self.emit("intrusion", {"zone": intruder})
        for zone in self.armed.pop_passed():   # appeared while armed and gone before the hold was over
            self.emit("passed_by", {"zone": zone})

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
        for i, link in enumerate(self.links):
            drop = (self.window["links"].get(link) or {}).get("drop_db") or 0.0
            raw[link] = float(self.model._link_weight[i]) * abs(drop)
        top = max(raw.values()) or 1.0
        return {link: round(v / top, 2) for link, v in raw.items()}

    def state(self) -> dict:
        now = self.now()
        self._tick()
        # A baseline asked for by hand measures the rates again; the old ones don't judge it.
        health = self.health.update(now, self.raw_kind, self.router == HOME, self.capture is not None,
                                    rates_known=not (self.capture and self.capture["new_place"]))
        self._health_ok = health["health"]["status"] == "ok"
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
        self._update_advice(now, xray, links)
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
        return state
