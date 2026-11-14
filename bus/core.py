"""Message bus and session recorder.

    python -m bus
    python -m bus --port 5600 --forward 127.0.0.1:5601 --sessions data/sessions

Every message that arrives on UDP 5600 (CONTRACTS.md sections 1, 2 and 4) gets
recv_t (board epoch ms at arrival), is counted against its producer's seq, and
is forwarded to the brain on 127.0.0.1:5601.

Recording: a cmd record_start {session, purpose, walker} opens
data/sessions/<session>.jsonl and writes a meta line built from its args. Every
message after that is appended, with recv_t, until record_stop. The brain gets
cmd messages from the screen on its own path, so the bus never forwards them.

An open recording outlives the bus process: data/sessions/.open names it until
record_stop, so a bus that crashed or was restarted carries on appending to the
same file (if it was written to in the last RESUME_WITHIN_S seconds) and says so.

A producer is one sending socket (address and port). Each process should send
from a single socket for its whole life, or its seq gaps can't be counted.
"""
import argparse
import json
import logging
import os
import re
import signal
import socket
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESSIONS_DIR = REPO / "data" / "sessions"
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PURPOSES = {"train", "heldout", "object", "crowd", "demo"}
MAX_DATAGRAM = 65535
OPEN_MARK = ".open"
RESUME_WITHIN_S = 600

log = logging.getLogger("bus")


def now_ms() -> int:
    return int(time.time() * 1000)


def encode(msg: dict) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode()


class Producer:
    """Seq bookkeeping for one sending socket."""

    def __init__(self, type_: str, src):
        self.type = type_
        self.src = src
        self.received = 0
        self.lost = 0
        self.restarts = 0
        self.last_seq = None

    def see(self, seq) -> int:
        """Count one message. Returns how many were lost just before it."""
        self.received += 1
        if not isinstance(seq, int) or isinstance(seq, bool):
            return 0
        gap = 0
        if self.last_seq is not None:
            if seq > self.last_seq + 1:
                gap = seq - self.last_seq - 1
                self.lost += gap
            elif seq <= self.last_seq:
                # The process restarted (or UDP reordered); start counting again.
                self.restarts += 1
        self.last_seq = seq
        return gap


class Recorder:
    """Appends messages to data/sessions/<session>.jsonl while a session is open."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.mark = self.folder / OPEN_MARK
        self.session = None
        self.lines = 0
        self._file = None

    @property
    def recording(self) -> bool:
        return self._file is not None

    def start(self, session: str, meta: dict) -> Path:
        self.stop()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{session}.jsonl"
        self._file = open(path, "a", encoding="utf-8", newline="\n")
        self.session = session
        self.lines = 0
        tmp = self.mark.with_name(OPEN_MARK + ".tmp")
        tmp.write_text(json.dumps({"session": session}), encoding="utf-8")
        os.replace(tmp, self.mark)
        self.write(meta)
        return path

    def resume(self, now: float) -> str | None:
        """Reopen the recording a bus before this one left open. Returns its session id, or None.

        The meta line is already in the file, so it just carries on. A mark whose file hasn't been
        written to for RESUME_WITHIN_S is stale (the bus was off for a while) and is dropped.
        """
        try:
            session = json.loads(self.mark.read_text(encoding="utf-8"))["session"]
        except (OSError, ValueError, KeyError, TypeError):
            return None
        path = self.folder / f"{session}.jsonl"
        try:
            fresh = isinstance(session, str) and SESSION_ID.match(session) and \
                now - path.stat().st_mtime <= RESUME_WITHIN_S
        except OSError:
            fresh = False
        if not fresh:
            self.mark.unlink(missing_ok=True)
            return None
        self._file = open(path, "a", encoding="utf-8", newline="\n")
        self.session = session
        self.lines = 0
        return session

    def write(self, msg: dict) -> None:
        if self._file is None:
            return
        self._file.write(json.dumps(msg, separators=(",", ":")) + "\n")
        self._file.flush()
        self.lines += 1

    def stop(self) -> None:
        """record_stop: close the file and forget it."""
        self.close()
        self.mark.unlink(missing_ok=True)

    def close(self) -> None:
        """The process is ending: close the file but keep the mark, so the next bus carries on."""
        if self._file is not None:
            self._file.close()
        self._file = None
        self.session = None


class Bus:
    def __init__(self, sessions=SESSIONS_DIR, send=None, clock=now_ms):
        self.recorder = Recorder(sessions)
        resumed = self.recorder.resume(time.time())  # file times are wall-clock
        if resumed:
            log.warning("the bus restarted while recording %s: appending to it again", resumed)
        self.producers: dict[str, Producer] = {}
        self.bad = 0
        self.send = send or (lambda data: None)
        self.clock = clock
        self.seq = 0  # our own counter, for the meta lines we write
        self._lost_at_start = 0
        self._warned = set()

    def lost(self) -> int:
        return sum(p.lost for p in self.producers.values())

    def handle(self, data: bytes, addr) -> dict | None:
        """Process one datagram. Returns the stamped message, or None if dropped."""
        recv_t = self.clock()
        key = f"{addr[0]}:{addr[1]}"
        try:
            msg = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return self._drop(key, "not JSON")
        if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
            return self._drop(key, "no type")
        if msg.get("v") != 2:
            return self._drop(key, f"v={msg.get('v')!r}, expected 2")
        msg["recv_t"] = recv_t

        if msg["type"] == "cmd":
            self.command(msg, recv_t)
            return msg

        producer = self.producers.get(key)
        if producer is None:
            producer = self.producers[key] = Producer(msg["type"], msg.get("src"))
        gap = producer.see(msg.get("seq"))
        if gap:
            log.info("%s (%s) lost %d before seq %s", key, producer.type, gap, msg.get("seq"))

        self.recorder.write(msg)
        try:
            self.send(encode(msg))
        except OSError as e:
            log.warning("forward failed: %s", e)
        return msg

    def command(self, msg: dict, recv_t: int) -> None:
        cmd = msg.get("cmd")
        args = msg.get("args") if isinstance(msg.get("args"), dict) else {}
        if cmd == "record_start":
            self.start_session(args, recv_t)
        elif cmd == "record_stop":
            self.stop_session()
        else:
            # Other cmds (truth, label_mode, ...) are kept in the session for scoring.
            self.recorder.write(msg)

    def start_session(self, args: dict, recv_t: int) -> None:
        session = args.get("session")
        if not isinstance(session, str) or not SESSION_ID.match(session):
            log.warning("record_start ignored: bad session id %r", session)
            return
        purpose = args.get("purpose")
        if purpose not in PURPOSES:
            log.warning("record_start %s: unknown purpose %r", session, purpose)
        self.stop_session()
        self.seq += 1
        meta = {"v": 2, "type": "meta", "t": recv_t, "seq": self.seq, "src": "live",
                "session": session, "purpose": purpose, "walker": args.get("walker"),
                "recv_t": recv_t}
        path = self.recorder.start(session, meta)
        self._lost_at_start = self.lost()
        log.info("recording %s (%s) to %s", session, purpose, path)
        try:
            self.send(encode(meta))
        except OSError as e:
            log.warning("forward failed: %s", e)

    def stop_session(self) -> None:
        if not self.recorder.recording:
            return
        log.info("stopped %s: %d lines, %d lost in transit",
                 self.recorder.session, self.recorder.lines, self.lost() - self._lost_at_start)
        self.recorder.stop()

    def report(self) -> list[str]:
        lines = [f"{key} ({p.type}, {p.src}): {p.received} received, {p.lost} lost, "
                 f"{p.restarts} restarts" for key, p in sorted(self.producers.items())]
        if self.bad:
            lines.append(f"{self.bad} dropped (not contract v2)")
        return lines

    def close(self) -> None:
        if self.recorder.recording:
            log.info("closing with %s still recording: the next bus carries on with it (%d lines here)",
                     self.recorder.session, self.recorder.lines)
        self.recorder.close()

    def _drop(self, key: str, why: str) -> None:
        self.bad += 1
        if (key, why) not in self._warned:
            self._warned.add((key, why))
            log.warning("dropping from %s: %s", key, why)
        return None


def serve(bus: Bus, sock: socket.socket, stop=None, stats_every: float = 30.0) -> None:
    """Receive until stop (a threading.Event) is set, or forever."""
    sock.settimeout(0.25)
    next_report = time.monotonic() + stats_every
    while stop is None or not stop.is_set():
        try:
            data, addr = sock.recvfrom(MAX_DATAGRAM)
            bus.handle(data, addr)
        except socket.timeout:
            pass
        except ConnectionResetError:
            pass  # Windows reports an earlier unreachable send this way; harmless
        if time.monotonic() >= next_report:
            next_report += stats_every
            for line in bus.report():
                log.info(line)


def open_sockets(host: str, port: int, forward: tuple[str, int]):
    """The receive socket and a sender that forwards to the brain."""
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    except OSError:
        pass
    rx.bind((host, port))
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return rx, tx, (lambda data: tx.sendto(data, forward))


def parse_addr(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host or "127.0.0.1", int(port)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Radio Sight message bus and session recorder")
    ap.add_argument("--host", default="0.0.0.0", help="address to listen on")
    ap.add_argument("--port", type=int, default=5600)
    ap.add_argument("--forward", default="127.0.0.1:5601", help="where the brain listens")
    ap.add_argument("--sessions", default=str(SESSIONS_DIR), help="folder for <session>.jsonl")
    ap.add_argument("--stats-every", type=float, default=30.0, help="seconds between seq reports")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="bus: %(message)s", stream=sys.stderr)
    forward = parse_addr(args.forward)
    rx, tx, send = open_sockets(args.host, args.port, forward)
    bus = Bus(sessions=args.sessions, send=send)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    log.info("listening on %s:%d, forwarding to %s:%d", args.host, rx.getsockname()[1], *forward)
    try:
        serve(bus, rx, stats_every=args.stats_every)
    except KeyboardInterrupt:
        pass
    finally:
        bus.close()
        for line in bus.report():
            log.info(line)
        rx.close()
        tx.close()
