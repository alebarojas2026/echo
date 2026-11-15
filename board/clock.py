"""Setting the board's clock from the operator's laptop (#630, contract issue #632).

The desk has no internet and no time source, and the board has no clock battery, so its clock
can be minutes off, and every time a judge reads (Ask the room, the replay, the incident report)
comes from it. The operator's laptop has the right time.

    GET  /clock          {"t": board epoch ms, "busy": null or why a step is refused now, "last": ...}
    POST /clock {"t": n} 200 within 2 s (nothing happens), 202 stepping, 409 refused, 400, 503

board/serve.py answers both (ClockAPI below), as the clone's owner. It can't set the time, so
for a step it writes /run/radio-sight-clock/request.json, and the helper, a root unit
(`python -m board.clock helper`, radio-sight-clock), takes it: it stops the stack's units, sets
the clock, and starts again the ones that were running, in order. The brain times durations
with the wall clock, so a jump of minutes under a running brain would fire the no-movement
timer and time out a baseline; a fresh brain starts from its saved files (data/sessions:
baseline.json and model.pkl), the store is a file, and nothing that was open is lost because a
step is refused while anything is open.

Refused while armed, while a recording is open (a lesson is one), while a fit is running, while
a baseline is being captured (the bus marks a baseline cmd in data/sessions/.baseline; the
brain writes baseline.json when it's done), while the brain isn't answering, and while a step
is already under way.

    python -m board.clock      # one line: the board's time and whether a step would be refused

Standard library only.
"""
import argparse
import base64
import datetime
import json
import logging
import os
import socket
import subprocess
import sys
import time
from http import HTTPStatus
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN_DIR = Path(os.environ.get("CLOCK_RUN_DIR", "/run/radio-sight-clock"))
SESSIONS = REPO / "data" / "sessions"
STEP_OVER_MS = 2000                      # within 2 s nothing happens
T_MIN, T_MAX = 1_735_689_600_000, 4_102_444_800_000   # 2025-01-01 and 2100-01-01 UTC
BASELINE_OPEN_MS = 140_000               # the brain's 120 s give-up plus the 20 s capture
REQUEST_STALE_MS = 10_000
HELPER_ALIVE_MS = 5000
# Stopped in reverse and started in this order. The web server and the model server keep running:
# neither times anything with the wall clock, and the model takes long to load.
STACK = ["radio-sight-bus", "radio-sight-wifi-rssi", "radio-sight-hci-scan", "radio-sight-camwatch",
         "radio-sight-brain", "radio-sight-narrate", "radio-sight-privacy"]
NO_HELPER = "the clock helper isn't running"
log = logging.getLogger("clock")


class Unreadable(Exception):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


def _stamp(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


# ---- the brain's state, from its WebSocket (just enough of RFC 6455 to read one message) ----

def _frame(f):
    head = f.read(2)
    if len(head) < 2:
        raise Unreadable("the brain closed the connection")
    fin, op, n = head[0] & 0x80, head[0] & 0x0F, head[1] & 0x7F
    if n >= 126:
        ext = f.read(2 if n == 126 else 8)
        n = int.from_bytes(ext, "big")
    mask = f.read(4) if head[1] & 0x80 else None
    if n > 8 << 20:
        raise Unreadable("the brain sent a message too big to read")
    data = f.read(n)
    if mask:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return fin, op, data


def brain_state(host="127.0.0.1", port=8765, timeout=1.5) -> dict:
    """The next state message the brain sends (CONTRACTS.md section 5)."""
    key = base64.b64encode(os.urandom(16)).decode()
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall((f"GET /ws HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            f = s.makefile("rb")
            if b" 101 " not in f.readline():
                raise Unreadable("the brain refused the connection")
            while f.readline() not in (b"\r\n", b""):
                pass
            deadline, parts = time.monotonic() + timeout, []
            while time.monotonic() < deadline:
                fin, op, data = _frame(f)
                if op == 8:
                    raise Unreadable("the brain closed the connection")
                if op in (0, 1):
                    parts.append(data)
                    if fin:
                        doc = json.loads(b"".join(parts))
                        parts = []
                        if isinstance(doc, dict) and doc.get("type") == "state":
                            return doc
    except (OSError, ValueError) as e:
        raise Unreadable(f"the brain isn't answering ({e})") from None
    raise Unreadable("the brain sent no state in time")


# ---- what serve.py answers --------------------------------------------------------------

class ClockAPI:
    def __init__(self, run_dir=RUN_DIR, sessions=SESSIONS, state=brain_state, now=now_ms):
        self.run_dir, self.sessions = Path(run_dir), Path(sessions)
        self.state, self.now = state, now

    def busy(self, now: int):
        """None, or why a step would be refused now, in plain words."""
        ready = _read_json(self.run_dir / "ready.json")
        if not (isinstance(ready, dict) and _int(ready.get("t")) and abs(now - ready["t"]) <= HELPER_ALIVE_MS):
            return NO_HELPER
        if (self.run_dir / "request.json").exists():
            return "a clock step is already under way"
        mark = _read_json(self.sessions / ".open")
        if (self.sessions / ".open").exists():
            session = mark.get("session") if isinstance(mark, dict) else None
            return f"a recording is open ({session})" if isinstance(session, str) else "a recording is open"
        asked = _read_json(self.sessions / ".baseline")
        if isinstance(asked, dict) and _int(asked.get("asked_t")) and 0 <= now - asked["asked_t"] < BASELINE_OPEN_MS:
            done = _read_json(self.sessions / "baseline.json")
            if not (isinstance(done, dict) and _int(done.get("t")) and done["t"] >= asked["asked_t"]):
                return "a baseline is being captured"
        try:
            state = self.state()
        except Unreadable:
            return "the brain isn't answering"
        if state.get("armed") is True:
            return "armed: disarm first"
        training = (state.get("model") or {}).get("training")
        if training:
            return "a lesson is running" if training.get("lesson") else "a fit is running"
        return None

    def get(self):
        now = self.now()
        return HTTPStatus.OK, {"t": now, "busy": self.busy(now), "last": _read_json(self.run_dir / "result.json")}

    def post(self, body: bytes):
        try:
            t = json.loads(body)["t"]
            if not (_int(t) and T_MIN <= t < T_MAX):
                raise ValueError(t)
        except (ValueError, KeyError, TypeError):
            return HTTPStatus.BAD_REQUEST, {"ok": False, "why": 'send {"t": epoch ms}'}
        now = self.now()
        diff = t - now
        if abs(diff) <= STEP_OVER_MS:
            return HTTPStatus.OK, {"ok": True, "diff_ms": diff, "stepping": False}
        why = self.busy(now)
        if why == NO_HELPER:
            return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "why": why}
        if why:
            return HTTPStatus.CONFLICT, {"ok": False, "diff_ms": diff, "why": why}
        try:
            _write_json(self.run_dir / "request.json", {"offset_ms": diff, "asked_t": now})
        except OSError as e:
            log.warning("can't hand the step to the helper: %s", e)
            return HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "why": NO_HELPER}
        return HTTPStatus.ACCEPTED, {"ok": True, "diff_ms": diff, "stepping": True}


# ---- the root helper --------------------------------------------------------------------

def _systemctl(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=60)


def _set_clock(epoch_ms: int) -> None:
    time.clock_settime(time.CLOCK_REALTIME, epoch_ms / 1000)


class Helper:
    def __init__(self, run_dir=RUN_DIR, systemctl=_systemctl, set_clock=_set_clock, clock=time.time,
                 monotonic=time.monotonic):
        self.run_dir, self.systemctl, self.set_clock = Path(run_dir), systemctl, set_clock
        self.clock, self.monotonic = clock, monotonic

    def step_once(self):
        """Take a waiting request, if there is one. Returns the result written, or None."""
        req_path = self.run_dir / "request.json"
        if not req_path.exists():
            return None
        req = _read_json(req_path)
        req_path.unlink(missing_ok=True)
        now = int(self.clock() * 1000)
        if not (isinstance(req, dict) and _int(req.get("offset_ms")) and _int(req.get("asked_t"))):
            return self._done({"ok": False, "why": "the request couldn't be read", "t": now})
        if not 0 <= now - req["asked_t"] <= REQUEST_STALE_MS:
            return self._done({"ok": False, "why": "the request was too old; set it again", "t": now})
        target = now + req["offset_ms"]
        if not T_MIN <= target < T_MAX:
            return self._done({"ok": False, "why": "that time is out of range", "t": now})
        started = self.monotonic()
        running = [u for u in STACK if self.systemctl("is-active", "--quiet", f"{u}.service").returncode == 0]
        for unit in reversed(running):
            self.systemctl("stop", f"{unit}.service")
        before = int(self.clock() * 1000)
        try:
            self.set_clock(before + req["offset_ms"])
            why, stepped = None, req["offset_ms"]
        except OSError as e:
            why, stepped = f"the clock couldn't be set: {e}", 0
        failed = [u for u in running if self.systemctl("start", f"{u}.service").returncode != 0]
        after = int(self.clock() * 1000)
        if failed and not why:
            why = "these didn't start again: " + ", ".join(failed)
        result = {"ok": why is None, "t": after, "stepped_ms": stepped,
                  "took_s": round(self.monotonic() - started, 1), "units": running}
        if why:
            result["why"] = why
        log.info("clock: %s was %s, now %s; restarted %s in %.1f s%s", "stepped" if result["ok"] else "step",
                 _stamp(before), _stamp(after), ", ".join(running) or "nothing", result["took_s"],
                 f" ({why})" if why else "")
        return self._done(result)

    def _done(self, result: dict) -> dict:
        _write_json(self.run_dir / "result.json", result)
        return result

    def run(self, user=None, every_s=0.25) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if user:  # serve.py, as the clone's owner, writes its request here
            import pwd
            pw = pwd.getpwnam(user)
            os.chown(self.run_dir, pw.pw_uid, pw.pw_gid)
        (self.run_dir / "request.json").unlink(missing_ok=True)   # nothing asked before we started counts
        log.info("clock: ready; the board's clock is %s", _stamp(int(self.clock() * 1000)))
        last_ready = 0.0
        while True:
            if self.monotonic() - last_ready >= 1:
                _write_json(self.run_dir / "ready.json", {"t": int(self.clock() * 1000)})
                last_ready = self.monotonic()
            self.step_once()
            time.sleep(every_s)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The board's clock, set from the operator's laptop")
    ap.add_argument("what", nargs="?", default="show", choices=("show", "helper"))
    ap.add_argument("--user", help="helper: who may ask for a step (the clone's owner)")
    args = ap.parse_args(argv)
    if args.what == "helper":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        Helper().run(args.user)
        return 0
    _, doc = ClockAPI().get()
    print(f"board clock {_stamp(doc['t'])}; " + (f"a step would be refused: {doc['busy']}" if doc["busy"]
                                                 else "a step can be taken"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
