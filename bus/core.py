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

Every 30 s the log has a line per producer (received, lost, restarts) and one line with the rssi
rate of each link in radio/nodes.json, naming the links that sent nothing and, once the brain has
written data/sessions/baseline.json, the links under 0.4 x the rate the baseline counted (the
stale rule, CONTRACTS.md section 6). A link that was flowing and goes QUIET_S without a reading
gets a warning at once, and one line when it's back.

Losses are logged at most once per LOSS_LOG_S per producer, with the total since the last line:
in a crowded hall a reader can lose every other advert, and a log line per gap would cost more
than the messages themselves.

The witnesses (CONTRACTS.md section 13, #866): each chain_head, the board's "this is where the
sealed record stands", is also sent on, from the bus's own port, to every socket that sent a
chain_witness or a chain_sub in the last SUB_KEEP_S seconds, which is how a Pi behind the other
Pi's hotspot hears the board at all. A chain_sub is only a witness saying it is there: it goes no
further. chain_head and chain_witness go on to the brain like any message, but their seq is the
chain's record number, so no gaps are counted on them.

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
QUIET_S = 3.0
LOSS_LOG_S = 5.0
STALE_FRAC = 0.4
OPEN_MARK = ".open"
BASELINE_MARK = ".baseline"
CHAIN_KINDS = ("chain_sub", "chain_head", "chain_witness")
SUB_KEEP_S = 60
MAX_SUBS = 16
RESUME_WITHIN_S = 600

log = logging.getLogger("bus")


def load_link_ids(path=REPO / "radio" / "nodes.json") -> list:
    """The link ids in radio/nodes.json, in its order; [] if it can't be read."""
    try:
        return [link["id"] for link in json.loads(Path(path).read_text(encoding="utf-8"))["links"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def load_expected(path) -> dict:
    """{link: expected_hz} from the brain's baseline.json; {} when there's none or it can't be read."""
    try:
        links = json.loads(Path(path).read_text(encoding="utf-8"))["links"]
        return {k: float(v["expected_hz"]) for k, v in links.items()
                if isinstance(v, dict) and isinstance(v.get("expected_hz"), (int, float)) and v["expected_hz"] > 0}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


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
        self.unsaid = 0          # lost since the last loss line
        self.said_at = None      # recv_t of the last loss line

    def loss_line(self, gap: int, now_ms: int) -> int:
        """Count `gap` toward the next loss line; returns how many to say now (0 = not yet)."""
        self.unsaid += gap
        if self.said_at is not None and now_ms - self.said_at < LOSS_LOG_S * 1000:
            return 0
        said, self.unsaid, self.said_at = self.unsaid, 0, now_ms
        return said

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
        """Append one line. A write that fails (a full disk) ends the recording instead of the bus:
        it's said once, the file is let go and its mark removed, so a restarted bus doesn't pick
        the same file up and fail again. Forwarding to the brain doesn't depend on any of this."""
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(msg, separators=(",", ":")) + "\n")
            self._file.flush()
        except OSError as e:
            log.warning("recording %s stopped after %d lines: can't write to the file (%s). "
                        "The bus keeps forwarding; free some space and record again.", self.session, self.lines, e)
            self._let_go()
            self.mark.unlink(missing_ok=True)
            return
        self.lines += 1

    def _let_go(self) -> None:
        """Close the file, ignoring a flush that fails on a full disk."""
        f, self._file, self.session = self._file, None, None
        if f is not None:
            try:
                f.close()
            except OSError:
                pass

    def stop(self) -> None:
        """record_stop: close the file and forget it."""
        self.close()
        self.mark.unlink(missing_ok=True)

    def close(self) -> None:
        """The process is ending: close the file but keep the mark, so the next bus carries on."""
        self._let_go()


class Bus:
    def __init__(self, sessions=SESSIONS_DIR, send=None, clock=now_ms, reply=None):
        self.reply = reply or (lambda data, addr: None)   # sends from the listening socket
        self.chain_subs: dict = {}                        # a witness's (host, port) -> recv_t of its last message
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
        self.link_ids = load_link_ids()
        self.link_counts: dict = {}
        self.link_last: dict = {}     # link -> recv_t of its last reading
        self.link_quiet: set = set()  # links said to be quiet, not back yet

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

        chain = msg["type"] in CHAIN_KINDS
        if chain and self.chain(msg, tuple(addr[:2]), recv_t):
            return msg

        producer = self.producers.get(key)
        if producer is None:
            producer = self.producers[key] = Producer(msg["type"], msg.get("src"))
        if msg["type"] == "rssi" and isinstance(msg.get("link"), str):
            link = msg["link"]
            self.link_counts[link] = self.link_counts.get(link, 0) + 1
            if link in self.link_quiet:
                self.link_quiet.discard(link)
                log.info("%s back after %.0f s", link, (recv_t - self.link_last[link]) / 1000)
            self.link_last[link] = recv_t
        if chain:
            producer.received += 1   # seq is the chain's record number: nothing to count gaps on
            gap = 0
        else:
            gap = producer.see(msg.get("seq"))
        if gap:
            lost = producer.loss_line(gap, recv_t)
            if lost:
                log.info("%s (%s) lost %d before seq %s (%d lost in all)", key, producer.type, lost,
                         msg.get("seq"), producer.lost)

        # Forward first: the brain must get the reading whatever happens to the recording.
        try:
            self.send(encode(msg))
        except OSError as e:
            log.warning("forward failed: %s", e)
        self.recorder.write(msg)
        return msg

    def chain(self, msg: dict, addr: tuple, recv_t: int) -> bool:
        """The witnesses' part of a chain message: remember a witness's socket, send a head on to
        each of them. True when the message goes no further (chain_sub)."""
        for sub in [s for s, seen in self.chain_subs.items() if recv_t - seen > SUB_KEEP_S * 1000]:
            del self.chain_subs[sub]
        if msg["type"] != "chain_head":
            if addr in self.chain_subs or len(self.chain_subs) < MAX_SUBS:
                self.chain_subs[addr] = recv_t
            return msg["type"] == "chain_sub"
        data = encode(msg)
        for sub in self.chain_subs:
            if sub != addr:
                try:
                    self.reply(data, sub)
                except OSError as e:
                    log.warning("chain_head not sent on to %s:%s: %s", sub[0], sub[1], e)
        return False

    def command(self, msg: dict, recv_t: int) -> None:
        cmd = msg.get("cmd")
        args = msg.get("args") if isinstance(msg.get("args"), dict) else {}
        if cmd == "record_start":
            self.start_session(args, recv_t)
        elif cmd == "record_stop":
            self.stop_session()
        else:
            if cmd == "baseline":
                self.mark_baseline(recv_t)
            # Other cmds (truth, label_mode, ...) are kept in the session for scoring.
            self.recorder.write(msg)

    def mark_baseline(self, recv_t: int) -> None:
        """data/sessions/.baseline says when a baseline was last asked for; with the brain's
        baseline.json (written when it's done) board/clock.py can tell one is being captured."""
        mark = self.recorder.folder / BASELINE_MARK
        try:
            self.recorder.folder.mkdir(parents=True, exist_ok=True)
            tmp = mark.with_name(BASELINE_MARK + ".tmp")
            tmp.write_text(json.dumps({"asked_t": recv_t}), encoding="utf-8")
            os.replace(tmp, mark)
        except OSError as e:
            log.warning("can't mark the baseline (%s)", e)

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
        try:
            path = self.recorder.start(session, meta)
        except OSError as e:
            log.warning("record_start %s: can't open the recording (%s); nothing is recorded", session, e)
            self.recorder.stop()
            path = None
        self._lost_at_start = self.lost()
        if path is not None:
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

    def watch_links(self, now_ms: int) -> None:
        """Warn once when a link that was flowing has sent nothing for QUIET_S."""
        for link, last in self.link_last.items():
            if link not in self.link_quiet and now_ms - last >= QUIET_S * 1000:
                self.link_quiet.add(link)
                log.warning("%s quiet for %g s", link, QUIET_S)

    def link_report(self, seconds: float) -> str:
        """rssi per link since the last call, nodes.json order first, then the links that sent nothing."""
        counts, self.link_counts = self.link_counts, {}
        order = [link for link in self.link_ids if link in counts] + sorted(set(counts) - set(self.link_ids))
        flowing = ", ".join(f"{link} {counts[link] / seconds:.1f}/s" for link in order) or "no rssi"
        silent = [link for link in self.link_ids if link not in counts]
        expected = load_expected(self.recorder.folder / "baseline.json")
        stale = [link for link in order if link in expected and counts[link] / seconds < STALE_FRAC * expected[link]]
        return (f"links: {flowing}" + (f"; nothing from: {', '.join(silent)}" if silent else "")
                + (f"; under 0.4 x the baseline: {', '.join(stale)}" if stale else ""))

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
    next_watch = 0.0
    while stop is None or not stop.is_set():
        try:
            data, addr = sock.recvfrom(MAX_DATAGRAM)
            bus.handle(data, addr)
        except socket.timeout:
            pass
        except ConnectionResetError:
            pass  # Windows reports an earlier unreachable send this way; harmless
        if time.monotonic() >= next_watch:
            next_watch = time.monotonic() + 0.5
            bus.watch_links(now_ms())
        if time.monotonic() >= next_report:
            next_report += stats_every
            for line in bus.report():
                log.info(line)
            log.info(bus.link_report(stats_every))


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
    bus = Bus(sessions=args.sessions, send=send, reply=rx.sendto)
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
