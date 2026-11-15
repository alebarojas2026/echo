"""The sim feed for the soak: sim.send's loop with a playlist, in one process with one socket.

    python lab/soak/feeder.py 5610      # then write "<path> <seed>" lines on stdin

Paths play back to back at real speed with no gap between them (a new sim.send process per path
takes seconds to start on a busy machine, and the links would go stale in between). Prints
{"start": path} and {"end": path} lines, with "t", on stdout.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sim.fake import load_path, pace, simulate  # noqa: E402
from sim.send import UdpOut  # noqa: E402
from sim.wire import encoder  # noqa: E402


def main():
    out = UdpOut("127.0.0.1", int(sys.argv[1]))
    encode = encoder()   # one producer: seq keeps counting from path to path
    for line in sys.stdin:
        path, seed = line.split()
        start_ms = int(time.time() * 1000)
        print(json.dumps({"start": path, "t": time.time()}), flush=True)
        events = simulate(load_path(path), rate=15.0, seed=int(seed))
        pace(((e["t"], encode({**e, "t": e["t"] + start_ms / 1000})) for e in events), out=out)
        print(json.dumps({"end": path, "t": time.time()}), flush=True)


if __name__ == "__main__":
    main()
