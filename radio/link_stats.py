"""How much each link flutters with the square empty: per-link spread and drift from a recorded session.

    python -m radio.link_stats --capture 30                        # record 30 s through the bus, then print
    python -m radio.link_stats data/sessions/flutter1.jsonl        # print for a session already recorded

--capture sends record_start (purpose demo, which proof/ never scores) and record_stop to the bus on
127.0.0.1:5600, so radio-sight-bus must be running; the bus writes data/sessions/<session>.jsonl.
It refuses while the bus is recording something else, since record_start would end that recording.
Use 30 s for the spread and 600 s for the drift (#228).

Per link, over the rssi readings in the session (by recv_t):
    n, /s         readings and readings a second
    median        median dBm
    std           spread of the raw readings, dB
    std 0.5s      spread of the 0.5 s means, dB (what the steady rule in CONTRACTS.md section 6 looks at)
    drift         highest minus lowest 1-minute median, dB; __ under 2 minutes
"""
import argparse
import json
import os
import socket
import statistics
import sys
import time
from pathlib import Path

from .nodes import LINKS

REPO = Path(__file__).resolve().parent.parent
SESSIONS = REPO / "data" / "sessions"


def readings(lines) -> dict:
    """{link: [(recv_t ms, dbm), ...]} from session lines (JSON text). Anything else is skipped."""
    out: dict = {}
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "rssi" and isinstance(msg.get("dbm"), (int, float)):
            t = msg.get("recv_t", msg.get("t"))
            if isinstance(t, (int, float)):
                out.setdefault(msg.get("link"), []).append((t, msg["dbm"]))
    return out


def buckets(points, width_ms: float) -> list:
    """The readings in each width_ms slice, from the first reading on."""
    start, out = points[0][0], {}
    for t, dbm in points:
        out.setdefault(int((t - start) // width_ms), []).append(dbm)
    return [v for _, v in sorted(out.items())]


def link_stats(points) -> dict:
    points = sorted(points)
    values = [dbm for _, dbm in points]
    span_s = (points[-1][0] - points[0][0]) / 1000
    means = [statistics.fmean(v) for v in buckets(points, 500)]
    minutes = [statistics.median(v) for v in buckets(points, 60_000)] if span_s >= 120 else []
    return {
        "n": len(values),
        "rate": len(values) / span_s if span_s > 0 else None,
        "median": statistics.median(values),
        "std": statistics.pstdev(values),
        "std_half_s": statistics.pstdev(means) if len(means) > 1 else None,
        "drift": max(minutes) - min(minutes) if len(minutes) > 1 else None,
    }


def table(by_link: dict) -> str:
    def num(v, fmt):
        return "__" if v is None else format(v, fmt)

    order = [link for link in LINKS if link in by_link] + sorted(set(by_link) - set(LINKS), key=str)
    rows = [f"{'link':<15} {'n':>6} {'/s':>6} {'median':>7} {'std':>5} {'std 0.5s':>8} {'drift':>6}"]
    for link in order:
        s = link_stats(by_link[link])
        rows.append(f"{str(link):<15} {s['n']:>6} {num(s['rate'], '.1f'):>6} {s['median']:>7.1f} "
                    f"{s['std']:>5.2f} {num(s['std_half_s'], '.2f'):>8} {num(s['drift'], '.1f'):>6}")
    missing = [link for link in LINKS if link not in by_link]
    if missing:
        rows.append("no readings: " + ", ".join(missing))
    return "\n".join(rows)


def open_recording(sessions=None):
    """The session the bus is recording now (its data/sessions/.open mark), or None."""
    try:
        session = json.loads(((sessions or SESSIONS) / ".open").read_text(encoding="utf-8"))["session"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return session if isinstance(session, str) else None


def capture(session: str, seconds: float, bus=("127.0.0.1", 5600), sleep=time.sleep) -> None:
    """Have the bus record `seconds` of everything into data/sessions/<session>.jsonl."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def cmd(name, args):
        sock.sendto(json.dumps({"v": 2, "type": "cmd", "cmd": name, "args": args}).encode(), bus)

    try:
        cmd("record_start", {"session": session, "purpose": "demo", "walker": None})
        sleep(seconds)
        cmd("record_stop", {})
        sleep(1.0)  # let the bus close the file
    finally:
        sock.close()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="per-link spread and drift from a recorded session")
    ap.add_argument("path", nargs="?", help="a session .jsonl (or use --capture)")
    ap.add_argument("--capture", type=float, metavar="SECONDS", help="record this long through the bus first")
    ap.add_argument("--session", help="session id for --capture (default: flutter-<time>)")
    args = ap.parse_args(argv)
    if args.capture and open_recording():
        sys.exit(f"the bus is recording {open_recording()}: a capture would end that recording. "
                 "Stop it first (record_stop), then capture.")
    if args.capture:
        args.session = args.session or time.strftime("flutter-%H%M%S")  # a new file: the bus appends to an old one
        bus = (os.environ.get("BUS_HOST", "127.0.0.1"), int(os.environ.get("BUS_PORT", "5600")))
        print(f"recording {args.capture:g} s as {args.session}: keep the square empty", file=sys.stderr)
        capture(args.session, args.capture, bus)
        path = SESSIONS / f"{args.session}.jsonl"
    elif args.path:
        path = Path(args.path)
    else:
        ap.error("give a session file or --capture SECONDS")
    if not path.exists():
        sys.exit(f"{path} doesn't exist: is radio-sight-bus running? (systemctl status radio-sight-bus)")
    by_link = readings(path.read_text(encoding="utf-8").splitlines())
    if not by_link:
        sys.exit(f"{path} has no rssi readings: are the readers running?")
    print(table(by_link))


if __name__ == "__main__":
    main()
