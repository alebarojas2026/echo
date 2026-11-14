"""The brain's state machine: bus messages and screen commands in, section 5 state out.

No sockets here (brain/main.py has them), so every rule can be tested with a
fake clock. Times are board epoch ms, the same clock as the bus's recv_t.

Link health (brain/health.py) and the x-ray and objects (brain/xray.py) are
separate modules; this file feeds them and puts their output into the state.
Still to come, each with its own issue: check-in and the alert, recalibration
and drift, advice, and the narrator's enter/exit events.
"""
from __future__ import annotations

import json
import statistics
import time
from collections import deque
from pathlib import Path
from typing import Callable, Dict, List, Optional

from brain import features as F
from brain.health import Health
from brain.train import Model
from brain.xray import Xray

BASELINE_MS = 20_000
HOME = "S-home"
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
NO_ALERT = {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
CAM_SILENT_MS = 3_000
TEACHER_FRESH_MS = 1_000
TRAIN_PURPOSES = ("train", "object")
LABEL_MODES = ("person", "object", "off")


def now_ms() -> int:
    return int(time.time() * 1000)


class Brain:
    def __init__(self, clock: Optional[Callable[[], int]] = None, to_bus=None, mode_file=None,
                 spawn=None, board_stats=None, links=F.LINKS, nodes=None):
        """clock None = follow the feed (latest recv_t), for recorded files played fast.
        to_bus(msg) forwards a command to the bus.
        spawn(fit, done) runs fit() off the loop, then done(model) back on it.
        nodes is radio/nodes.json, already parsed (default: the repo's copy)."""
        nodes = nodes or json.loads(NODES_JSON.read_text(encoding="utf-8"))
        self.health = Health.from_nodes(nodes)
        self.xray = Xray.from_nodes(nodes)
        self._still_since: Optional[int] = None
        self._heard = False                   # any reading yet
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
        self.expected_hz: Dict[str, float] = {}
        self.windower: Optional[F.Windower] = None
        self.window: Optional[dict] = None
        self.capture: Optional[dict] = None   # a running baseline capture
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

    def now(self) -> int:
        return self._clock() if self._clock else self.feed_t

    # ---- inputs ----

    def on_message(self, msg: dict) -> None:
        """One message forwarded by the bus (it carries recv_t)."""
        t, kind = msg.get("recv_t"), msg.get("type")
        if t is None:
            return
        self.feed_t = max(self.feed_t, int(t))
        self.src = msg.get("src", self.src)
        if kind == "meta":
            # Only the meta the bus writes for our record_start opens a copy. The fake
            # feed sends its own meta (and again on every loop); those are ignored.
            if self.want_session is not None and msg.get("session") == self.want_session:
                self.open_session = {"meta": msg, "messages": []}
        elif kind == "cam":
            self.cam = (t, msg.get("state"))
        elif kind == "narration":
            self.narration = {k: msg.get(k) for k in ("text", "event_id", "t", "source", "gen_ms")}
        elif kind in ("rssi", "label"):
            if self.open_session is not None:
                self.open_session["messages"].append(msg)
            if kind == "label":
                self.label = msg
                if self.capture and (msg.get("persons_in_frame") or 0) > 0:
                    self._start_capture()  # someone walked in: start the 20 s again
            elif msg.get("link") in self.links:
                link, dbm = msg["link"], float(msg["dbm"])
                self.health.add(link, t, dbm)
                self._heard = True
                if link in self.base:
                    self.xray.add(link, t, self.base[link] - dbm)
                if self.capture:
                    if self.capture["start"] is None:
                        self.capture["start"] = t  # the 20 s run from the first reading
                    self.capture["messages"].append(msg)
            if self.windower:
                for window in self.windower.push(msg):
                    self.window = window
        self._tick()

    def on_cmd(self, msg: dict) -> None:
        """One command from the screen. Every command also goes to the bus, which records it."""
        cmd, args = msg.get("cmd"), msg.get("args") or {}
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler is None:
            return
        self._cmd_seq += 1
        self.to_bus({"v": 2, "type": "cmd", "t": self.now(), "seq": self._cmd_seq, "src": self.src,
                     "cmd": cmd, "args": args})
        handler(args)

    def _cmd_baseline(self, args):
        self._cmd_label_mode({"mode": "off"})
        self._start_capture()

    def _cmd_train(self, args):
        if self.training or not self.base:
            return
        sessions = [s for s in self.sessions.values() if s["meta"].get("purpose") in TRAIN_PURPOSES]
        if not sessions:
            return
        self.training = {"since_t": self.now(), "sessions": len(sessions)}
        base, ver = dict(self.base), f"m{self.model_n + 1}"

        def fit():   # may run on another thread: touches nothing of ours
            return Model(base, ver=ver).fit(sessions)

        def done(model):   # back on the loop; model None = the fit failed
            self.training = None
            if model is None:
                return
            self.model, self.model_n = model, self.model_n + 1
            self.decision_ms.clear()
            self.emit("trained", {"ver": ver, "train_s": model.info()["train_s"]})

        self.spawn(fit, done)

    def _cmd_relearn(self, args):
        """Forget the current model and train again from the recorded sessions."""
        self.model = self.pred = None
        self._cmd_train(args)

    def _cmd_reset_alert(self, args):
        self._still_since = None

    def _cmd_reset(self, args):
        """Between judges: clear the alert, still timer, check-in, advice and narration."""
        self._still_since = self.narration = None
        self.emit("reset", {})

    def _cmd_record_start(self, args):
        self.want_session = args.get("session")
        # The bus opens the file and sends back the meta message that opens our copy.
        self.emit("recording", {"on": True, "session": args.get("session")})

    def _cmd_record_stop(self, args):
        s, self.open_session, self.want_session = self.open_session, None, None
        session = s["meta"].get("session") if s else None
        if session:
            self.sessions[session] = s
        self.emit("recording", {"on": False, "session": session})

    def _cmd_label_mode(self, args):
        mode = args.get("mode")
        if mode not in LABEL_MODES:
            return
        self.label_mode = mode
        if self.mode_file:  # the camera teacher reads its mode from this file
            with open(self.mode_file, "w", encoding="utf-8") as f:
                f.write(mode + "\n")

    def _cmd_router_moved(self, args):
        self.router = args.get("spot") or "moved"
        self._move_router(self.router)
        self.emit("router_moved", {"spot": self.router})

    def _cmd_router_home(self, args):
        self.router = HOME
        self._move_router(HOME)
        self.emit("router_home", {})

    def _cmd_truth(self, args):
        self.truth = args.get("zone")

    # ---- rules ----

    def _move_router(self, spot):
        try:
            self.xray.set_router(spot)   # the x-ray's geometry follows the router
        except KeyError:
            pass                         # not a spot in nodes.json

    def _start_capture(self):
        self.capture = {"start": None, "messages": []}

    def _tick(self):
        now = self.now()
        if self.capture and self.capture["start"] is not None and now - self.capture["start"] >= BASELINE_MS:
            msgs, self.capture = self.capture["messages"], None
            base = F.baseline(msgs)
            if base:
                self.base = base
                for link in base:
                    n = sum(1 for m in msgs if m["link"] == link)
                    self.expected_hz[link] = round(n / (BASELINE_MS / 1000), 1)
                self.windower, self.window = F.Windower(base, self.links), None
                self.health.set_base(base)
                self.health.set_expected(self.expected_hz)
                self.xray.reset()
                self.emit("baseline_done", {"links": len(base)})
        self._decide(now)

    def _decide(self, now):
        if not (self.model and self.window):
            self.pred = self.raw_kind = self._still_since = None
            return
        if not self.window.get("decided"):   # the classifier runs on every new window
            t0 = time.perf_counter()
            self._raw = self.model.predict(self.window)
            self.decision_ms.append((time.perf_counter() - t0) * 1000)
            self.window["decided"] = True
            self.raw_kind = self._raw["kind"]   # health wants this even while pred is hidden
            self._fresh = True
        if self.capture or self.router != HOME or self.health.blind:
            self.pred = self._still_since = None   # hidden; SENSOR BLIND never reads as "empty"
            return
        if not self._fresh:
            return
        self._fresh = False
        pred = dict(self._raw)
        still = pred["kind"] == "person" and pred["motion"] == "still"
        if not still or (self.pred and self.pred["zone"] != pred["zone"]):
            self._still_since = None
        if still and self._still_since is None:
            self._still_since = self.window["end"]
        pred["still_s"] = round((self.window["end"] - self._still_since) / 1000, 1) if still else 0.0
        self.pred = pred

    def emit(self, kind: str, info: dict) -> None:
        self._seq += 1
        self._event_n += 1
        self.events.append({"v": 2, "type": "event", "t": self.now(), "seq": self._seq, "src": self.src,
                            "id": f"e{self._event_n}", "kind": kind, "info": info})

    def pop_events(self) -> List[dict]:
        out, self.events = self.events, []
        return out

    # ---- output ----

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
        health = self.health.update(now, self.raw_kind, self.router == HOME, self.capture is not None)
        if self.health.blind:
            self.pred = self._still_since = None
        # Section 5: xray is null before the first baseline, links are [] before any reading.
        xray = self.xray.update(now, self.pred["kind"] if self.pred else None) if self.base else \
            {"xray": None, "objects": [], "events": []}
        for e in health["events"] + xray["events"]:
            self.emit(e["kind"], e["info"])
        weights = self._why_weights()
        links = [dict(row, why=weights.get(row["id"], 0.0)) for row in health["links"]] if self._heard else []
        self._seq += 1
        cam = self.cam[1] if self.cam and now - self.cam[0] <= CAM_SILENT_MS else "off"
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
                "alert": dict(NO_ALERT), "checkin": None, "advice": None, "narration": self.narration, "teacher": teacher,
                "model": model, "board": self.board_stats()}
