"""Play a recorded JSON-lines file back at real speed.

    python -m sim.replay data/sessions/tour.jsonl
    python -m sim.replay data/sessions/tour.jsonl --speed 4 --loop

Works on files made by `python -m sim.fake NAME --fast` and on sessions the
bus recorded. Lines come out with src "replay" and without recv_t; everything
else is unchanged. Pacing follows recv_t when a line has it, otherwise t.
"""
import argparse
import sys

from .fake import pace
from .wire import as_replay, time_of


def read(file):
    """Yield (t, line) for every non-blank line of an open file."""
    for line in file:
        line = line.strip()
        if line:
            yield time_of(line), as_replay(line)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", help="recorded .jsonl file")
    ap.add_argument("--speed", type=float, default=1.0, help="2 = twice as fast")
    ap.add_argument("--loop", action="store_true", help="start over at the end, forever")
    args = ap.parse_args(argv)
    try:
        while True:
            with open(args.file) as f:
                pace(read(f), out=sys.stdout, speed=args.speed)
            if not args.loop:
                break
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
