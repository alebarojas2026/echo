"""Send the fake feed to the bus over UDP at real speed, so the whole system runs with no hardware.

    python -m sim.send zone_tour                      # a scripted path, src "sim"
    python -m sim.send data/sessions/s12.jsonl        # a recording, src "replay", seq renumbered
    python -m sim.send zone_tour --loop --speed 2

One JSON message per datagram, to 127.0.0.1:5600 (the bus, CONTRACTS.md section 2).
"""
import argparse
import itertools
import socket
import time

from .fake import load_path, lossy, pace, simulate
from .replay import read
from .wire import encoder

BUS = ("127.0.0.1", 5600)


class UdpOut:
    """Looks like a file to `pace`; every line written becomes one datagram."""

    def __init__(self, host: str, port: int):
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sent = 0

    def write(self, text: str) -> None:
        self.sock.sendto(text.strip().encode(), self.addr)
        self.sent += 1

    def flush(self) -> None:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="path name, path JSON file, or a recorded .jsonl file")
    ap.add_argument("--host", default=BUS[0])
    ap.add_argument("--port", type=int, default=BUS[1])
    ap.add_argument("--rate", type=float, default=15.0, help="readings per link per second (10-20)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    ap.add_argument("--loop", action="store_true", help="start over at the end, forever")
    ap.add_argument("--loss", type=float, default=0.0, help="share of messages to drop, e.g. 0.05")
    args = ap.parse_args(argv)
    out = UdpOut(args.host, args.port)
    encode = encoder()  # one producer: seq keeps counting across loops
    replay_seq = itertools.count(1)  # same for a recording: one socket, one fresh counter
    try:
        while True:
            if args.source.endswith(".jsonl"):
                with open(args.source) as f:
                    pace(read(f, replay_seq), out=out, speed=args.speed)
            else:
                start_ms = int(time.time() * 1000)
                events = simulate(load_path(args.source), rate=args.rate, seed=args.seed)
                lines = ((e["t"], encode({**e, "t": e["t"] + start_ms / 1000})) for e in events)
                pace(lossy(lines, args.loss, args.seed), out=out, speed=args.speed)
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass
    return out.sent


if __name__ == "__main__":
    main()
