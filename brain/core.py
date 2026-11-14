"""The brain's state machine: bus messages and screen commands in, section 5 state out.

No sockets here (brain/main.py has them), so every rule can be tested with a
fake clock. Times are board epoch ms, the same clock as the bus's recv_t.

Not in this file yet, each has its own issue: link health and SENSOR BLIND,
the x-ray and objects, check-in and the alert, recalibration and drift, and
the narrator's enter/exit events. Their state fields are sent empty for now.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from typing import Callable, Dict, List, Optional

from brain import features as F
from brain.train import Model

BASELINE_MS = 20_000
HOME = "S-home"
RATE_WINDOW_MS = 2_000
STALE_FRACTION = 0.4
CAM_SILENT_MS = 3_000
TEACHER_FRESH_MS = 1_000
TRAIN_PURPOSES = ("train", "object")
LABEL_MODES = ("person", "object", "off")


def now_ms() -> int:
    return int(time.time() * 1000)


class Brain:
    def __init__(self, clock: Optional[Callable[[], int]] = None, to_bus=None, mode_file=None,
                 spawn=None, board_stats=None, links=F.LINKS):
        """clock None = follow the feed (latest recv_t), for recorded files played fast.
        to_bus(msg) forwards a command to the bus. spawn(job) runs training off the loop."""
        self._clock = clock
        self.to_bus = to_bus or (lambda msg: None)
        self.mode_file = mode_file
        self.spawn = spawn or (lambda job: job())
        self.board_stats = board_stats or (lambda: {"cpu_temp_c": None, "cpu_mhz": None, "cpu_pct": None})
        self.links = tuple(links)
        self.feed_t = 0
        self.src = "live"
        self.history: Dict[str, deque] = {link: deque() for link in self.links}  # (recv_t, dbm)
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
        self._still_since: Optional[int] = None
        self.sessions: Dict[str, dict] = {}
        self.open_session: Optional[dict] = None
        self.router = HOME
        self.label_mode = "off"
        self.truth = None
        self.cam = None        # (recv_t, state)
        self.label = None      # the latest camera label
        self.narration = None
        self.events: List[dict] = []
        self._seq = {"state": 0, "event": 0, "cmd": 0}

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
            elif msg.get("link") in self.history:
                self.history[msg["link"]].append((t, float(msg["dbm"])))
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
        self._seq["cmd"] += 1
        self.to_bus({"v": 2, "type": "cmd", "t": self.now(), "seq": self._seq["cmd"], "src": self.src,
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

        def job():
            try:
                model = Model(base, ver=ver).fit(sessions)
            except Exception:
                self.training = None
                raise
            self.model, self.model_n, self.training = model, self.model_n + 1, None
            self.decision_ms.clear()
            self.emit("trained", {"ver": ver, "train_s": model.info()["train_s"]})

        self.spawn(job)

    def _cmd_relearn(self, args):
        """Forget the current model and train again from the recorded sessions."""
        self.model = self.pred = None
        self._cmd_train(args)

    def _cmd_reset_alert(self, args):
        self._still_since = None

    def _cmd_record_start(self, args):
        pass  # the bus opens the file and sends back the meta message that opens our copy

    def _cmd_record_stop(self, args):
        s, self.open_session = self.open_session, None
        if s and s["meta"].get("session"):
            self.sessions[s["meta"]["session"]] = s

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
        self.emit("router_moved", {"spot": self.router})

    def _cmd_router_home(self, args):
        self.router = HOME
        self.emit("router_home", {})

    def _cmd_truth(self, args):
        self.truth = args.get("zone")

    # ---- rules ----

    def _start_capture(self):
        self.capture = {"start": None, "messages": []}

    def _tick(self):
        now = self.now()
        for q in self.history.values():
            while q and q[0][0] < now - 10_000:
                q.popleft()
        if self.capture and self.capture["start"] is not None and now - self.capture["start"] >= BASELINE_MS:
            msgs, self.capture = self.capture["messages"], None
            base = F.baseline(msgs)
            if base:
                self.base = base
                for link in base:
                    n = sum(1 for m in msgs if m["link"] == link)
                    self.expected_hz[link] = round(n / (BASELINE_MS / 1000), 1)
                self.windower, self.window = F.Windower(base, self.links), None
                self.emit("baseline_done", {"links": len(base)})
        self._decide(now)

    def _decide(self, now):
        if not (self.model and self.window) or self.capture or self.router != HOME:
            self.pred, self._still_since = None, None
            return
        if self.window.get("decided"):
            return
        t0 = time.perf_counter()
        pred = self.model.predict(self.window)
        self.decision_ms.append((time.perf_counter() - t0) * 1000)
        self.window["decided"] = True
        still = pred["kind"] == "person" and pred["motion"] == "still"
        if not still or (self.pred and self.pred["zone"] != pred["zone"]):
            self._still_since = None
        if still and self._still_since is None:
            self._still_since = self.window["end"]
        pred["still_s"] = round((self.window["end"] - self._still_since) / 1000, 1) if still else 0.0
        self.pred = pred

    def emit(self, kind: str, info: dict) -> None:
        self._seq["event"] += 1
        n = self._seq["event"]
        self.events.append({"v": 2, "type": "event", "t": self.now(), "seq": n, "src": self.src,
                            "id": f"e{n}", "kind": kind, "info": info})

    def pop_events(self) -> List[dict]:
        out, self.events = self.events, []
        return out

    # ---- output ----

    def _links(self, now) -> List[dict]:
        weights = self._why_weights()
        out = []
        for link in self.links:
            recent = [d for t, d in self.history[link] if t > now - RATE_WINDOW_MS]
            last_s = [d for t, d in self.history[link] if t > now - 1000]
            dbm = round(statistics.median(last_s), 1) if last_s else None
            base = self.base.get(link)
            expected = self.expected_hz.get(link)
            rate = round(len(recent) / (RATE_WINDOW_MS / 1000), 1)
            stale = rate == 0 or (expected is not None and rate < STALE_FRACTION * expected)
            out.append({"id": link, "dbm": dbm, "base_dbm": base,
                        "drop_db": None if dbm is None or base is None else round(base - dbm, 1),
                        "rate_hz": rate, "expected_hz": expected,
                        "status": "stale" if stale else "ok", "why": weights.get(link, 0.0)})
        return out

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
        self._seq["state"] += 1
        cam = self.cam[1] if self.cam and now - self.cam[0] <= CAM_SILENT_MS else "off"
        lb = self.label
        teacher = None
        if cam == "on" and lb and now - lb["recv_t"] <= TEACHER_FRESH_MS and not lb.get("clipped"):
            teacher = {"present": bool(lb.get("present")), "zone": lb.get("zone") or 0, "motion": lb.get("motion")}
        model = self.model.info() if self.model else {"trained": False, "ver": None, "train_s": None,
                                                      "windows": 0, "train_sessions": []}
        model["ms_per_decision"] = round(statistics.median(self.decision_ms), 2) if self.decision_ms else None
        model["training"] = self.training
        return {"v": 2, "type": "state", "t": now, "seq": self._seq["state"], "src": self.src,
                "cam": cam, "router": self.router, "links": self._links(now),
                "health": {"status": "ok", "blind": [], "reason": None},
                "pred": self.pred, "objects": [], "xray": None,
                "alert": {"state": "none", "zone": None, "still_s": 0.0, "limit_s": None},
                "checkin": None, "advice": None, "narration": self.narration, "teacher": teacher,
                "model": model, "board": self.board_stats()}
