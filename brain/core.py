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
from brain.alert import Watch
from brain.health import Health
from brain.train import Model
from brain.xray import Xray

BASELINE_MS = 20_000
HOME = "S-home"
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
CAM_SILENT_MS = 3_000
TEACHER_FRESH_MS = 1_000
LINK_FRESH_MS = 1_000
WIFI = "pi5>unoq:wifi"
SETTLE_MS = 3_000        # after router_home, pi5 links must sit near base this long
SETTLE_DB = 1.0          # ... within this of base, else an automatic baseline runs
ADVICE_MEDIAN_MS = 3_000 # before_dbm and after_dbm are medians over this long
AFTER_START_MS = 2_000   # after_dbm starts this long after router_moved
SAME_OBJECT_M = 0.5      # an advice this close to the one showing is about the same object (the x-ray's match)
ZONE_HOLD = 5            # decisions in a row (0.5 s) before enter, exit or zone_change is said
TRAIN_PURPOSES = ("train", "object")
EVENT_INFO = ("zone", "link", "node", "before_dbm", "after_dbm", "on", "session")   # contracts/schemas/event.json
LABEL_MODES = ("person", "object", "off")


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


def _same_object(a, b) -> bool:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= SAME_OBJECT_M


def _is_reading(dbm) -> bool:
    return isinstance(dbm, (int, float)) and not isinstance(dbm, bool) and math.isfinite(dbm)


def now_ms() -> int:
    return int(time.time() * 1000)


class Brain:
    def __init__(self, clock: Optional[Callable[[], int]] = None, to_bus=None, mode_file=None,
                 spawn=None, board_stats=None, links=F.LINKS, nodes=None, led=None, sessions_dir=None):
        """clock None = follow the feed (latest recv_t), for recorded files played fast.
        to_bus(msg) forwards a command to the bus.
        spawn(fit, done) runs fit() off the loop, then done(model) back on it.
        nodes is radio/nodes.json, already parsed (default: the repo's copy).
        led is the LED grid (brain/alert.py); None = no lights.
        sessions_dir is data/sessions: baseline.json is written there and read back at start."""
        nodes = nodes or json.loads(NODES_JSON.read_text(encoding="utf-8"))
        self.health = Health.from_nodes(nodes)
        self.xray = Xray.from_nodes(nodes)
        self.watch = Watch({z["id"]: z.get("still_alert_s") for z in nodes["zones"]}, led)
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
        self.place_t: Optional[int] = None    # when the operator's last baseline finished: "this place"
        self.expected_hz: Dict[str, float] = {}
        self.windower: Optional[F.Windower] = None
        self.window: Optional[dict] = None
        self.capture: Optional[dict] = None   # a running baseline capture
        self._wait_said = ()                  # what the log last said the capture is waiting for
        self.model: Optional[Model] = None
        self.model_n = 0
        self.training: Optional[dict] = None
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

    def now(self) -> int:
        return self._clock() if self._clock else self.feed_t

    # ---- inputs ----

    def on_message(self, msg: dict) -> None:
        """One message forwarded by the bus (it carries recv_t)."""
        t, kind = msg.get("recv_t"), msg.get("type")
        if t is None:
            return
        if kind == "rssi" and not _is_reading(msg.get("dbm")):
            return   # no number, or NaN (JSON lets it through): one such reading in a baseline would poison it
        self.feed_t = max(self.feed_t, int(t))
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
            self.cam = (t, msg.get("state"))
        elif kind == "narration":
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
        model and the recordings made before it are dropped from use. The files stay on disk."""
        self._cmd_label_mode({"mode": "off"})
        self._start_capture(new_place=True)

    def _cmd_train(self, args):
        if self.training or not self.base:
            return
        self._find_sessions()
        sessions = [dict(s) for s in self.sessions.values() if s["meta"].get("purpose") in TRAIN_PURPOSES]
        if not sessions:
            return
        self.training = {"started_t": self.now(), "progress": None,
                         "sessions": sorted(s["meta"]["session"] for s in sessions)}
        base, ver, place = dict(self.base), f"m{self.model_n + 1}", self.place_t

        def fit():   # may run on another thread: touches nothing of ours
            for s in sessions:   # read back from the bus's files; nothing is kept after the fit
                if s["messages"] is None:
                    s["messages"] = read_session(s["path"], s["meta"].get("recv_t"))
            return Model(base, ver=ver).fit(sessions)

        def done(model):   # back on the loop; model None = the fit failed
            self.training = None
            if model is None or place != self.place_t:
                return   # the fit failed, or the place changed while it ran: that model is for the old one
            self.model, self.model_n = model, self.model_n + 1
            self._save_model()
            self.decision_ms.clear()
            if self.window:
                self.window["decided"] = False   # the new model decides on the next tick
            self.emit("trained", {"ver": ver, "train_s": model.info()["train_s"]})

        self.spawn(fit, done)

    def _cmd_relearn(self, args):
        """Forget the current model and train again from this place's recorded sessions."""
        self.model = self.pred = None
        self._cmd_train(args)

    def _cmd_reset_alert(self, args):
        self.watch.reset_alert()
        self._watch_events()

    def _cmd_reset(self, args):
        """Between judges: clear the alert, still timer, check-in, advice and narration."""
        self.watch.reset()
        self._dismissed = self.advice["xy_m"] if self.advice else None
        self.narration = self.advice = None
        self._watch_events()
        self.emit("reset", {})

    def _cmd_record_start(self, args):
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
        self.router = args.get("spot") or "moved"
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
        vals = [d for t, d in self._recent[link] if t >= t0 and (t1 is None or t < t1)]
        return round(statistics.median(vals), 1) if vals else None

    def _check_settle(self, now) -> None:
        """3 s after router_home: every pi5 link within 1 dB of base, or recalibrate."""
        if self.settle is None or now - self.settle < SETTLE_MS:
            return
        start, self.settle = self.settle, None
        for link in self.links:
            if "pi5" in link:
                m = self._median(link, start)
                if m is None or abs(m - self.base[link]) > SETTLE_DB:
                    self.recalibrating, self._old_base = True, dict(self.base)
                    self._cmd_label_mode({"mode": "off"})
                    self._start_capture(new_place=False)
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
        # place.json: when this place began (the last baseline asked for by hand). proof/ and a
        # restart use recordings from then on only. An automatic baseline leaves it alone.
        (self.sessions_dir / "place.json").write_text(json.dumps({"t": self.place_t}) + "\n", encoding="utf-8")

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

    def _start_capture(self, new_place: Optional[bool] = None):
        """new_place None = keep what the running capture was asked for (a restart of its 20 s)."""
        if new_place is None:
            new_place = bool(self.capture and self.capture["new_place"])
        self.capture = {"start": None, "messages": [], "new_place": new_place}

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
            if not self.recalibrating:
                return "the camera is not on"
        elif lb is None or now - lb["recv_t"] > TEACHER_FRESH_MS:
            return "no camera labels in the last second"
        elif (lb.get("persons_in_frame") or 0) != 0:
            return "the camera sees somebody"
        if self.label_mode != "off":
            return f"label mode is {self.label_mode}, not off"
        quiet = [link for link in self.links if now - self._last_seen.get(link, -10**15) > LINK_FRESH_MS]
        if quiet:
            return "no readings in the last second from " + ", ".join(quiet)
        if not self._health_ok or self.health.blind:
            return "link health is not ok"
        return None

    def _tick(self):
        now = self.now()
        if self.capture:
            wait = self._capture_wait(now)
            if wait != self._wait_said:             # said once per reason, not on every message
                self._wait_said = wait
                log = logging.getLogger("brain")
                log.warning("baseline is waiting: %s", wait) if wait else log.info("baseline: capturing 20 s")
            if wait:
                self._start_capture()               # a condition broke: the 20 s start again
            elif self.capture["start"] is None:
                self.capture["start"] = now
            elif now - self.capture["start"] >= BASELINE_MS:
                msgs, new_place, self.capture = self.capture["messages"], self.capture["new_place"], None
                self._wait_said = ()
                expected = {link: round(sum(1 for m in msgs if m["link"] == link) / (BASELINE_MS / 1000), 1)
                            for link in self.links}
                self._set_baseline(F.baseline(msgs), expected)
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
            return
        if not self._fresh:
            return
        self._fresh = False
        pred = dict(self._raw)
        self.watch.on_pred(self.window["end"], pred)
        pred["still_s"] = round(self.watch.still_ms / 1000, 1)
        self.pred = pred
        self._announce(pred["zone"] if pred["present"] else 0)

    def _announce(self, zone: int) -> None:
        """enter, exit and zone_change, once the new zone has held for ZONE_HOLD decisions.

        One flickering decision is not somebody walking in. Hidden spans (pred null) are skipped:
        whatever holds once pred is back gets announced then.
        """
        if zone == self._said_zone:
            self._next_zone = (zone, 0)
            return
        n = self._next_zone[1] + 1 if self._next_zone[0] == zone else 1
        self._next_zone = (zone, n)
        if n < ZONE_HOLD:
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
        # Section 5: xray is null before the first baseline, links are [] before any reading.
        xray = self.xray.update(now, self.pred["kind"] if self.pred else None) if self.base else \
            {"xray": None, "objects": [], "events": []}
        for e in health["events"] + xray["events"]:
            self.emit(e["kind"], e["info"])
        self._watch_events()
        weights = self._why_weights()
        links = [self._link_row(row, weights) for row in health["links"]
                 if row["id"] in self._heard]   # a link is listed once it has a reading
        self._update_advice(now, xray, links)
        cam = self.cam[1] if self.cam and now - self.cam[0] <= CAM_SILENT_MS else "off"
        if cam != self._said_cam and cam in ("on", "off", "stalled"):
            self._said_cam = cam
            self.emit(f"cam_{cam}", {})
        self._seq += 1
        lb = self.label
        teacher = None
        if cam == "on" and lb and now - lb["recv_t"] <= TEACHER_FRESH_MS and not lb.get("clipped"):
            teacher = {"present": bool(lb.get("present")), "zone": lb.get("zone") or 0, "motion": lb.get("motion")}
        model = self.model.info() if self.model else {"trained": False, "ver": None, "train_s": None,
                                                      "windows": 0, "train_sessions": []}
        model["ms_per_decision"] = round(statistics.median(self.decision_ms), 2) if self.decision_ms else None
        model["training"] = self.training
        return {"v": 2, "type": "state", "t": now, "seq": self._seq, "src": self.src,
                "cam": cam, "router": self.router, "links": links,
                "health": health["health"],
                "pred": self.pred, "objects": xray["objects"], "xray": xray["xray"],
                "alert": self.watch.alert_block(), "checkin": self.watch.checkin, "advice": self.advice and dict(self.advice), "narration": self.narration, "teacher": teacher,
                "model": model, "board": self.board_stats()}
