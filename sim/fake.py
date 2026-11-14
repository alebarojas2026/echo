"""Fake Radio Sight data: RSSI for every link plus matching camera labels.

    python -m sim.fake zone_tour            # real time, JSON lines on stdout
    python -m sim.fake zone_tour --fast > data/sessions/tour.jsonl

Room: a 2 x 2 m floor square, origin at one corner, metres.

    y=2 +-----n2-----+      zones:  2 | 3
        |  2  |  3   |              --+--
        n3----+-----n1              0 | 1
        |  0  |  1   |
    y=0 +-----n0-----+
       x=0          x=2

Four nodes sit at the midpoints of the sides, giving 6 links. Each diagonal
link crosses exactly one zone, so zones are distinguishable from RSSI alone.
"""
import argparse
import json
import math
import random
import sys
import time
from itertools import combinations
from pathlib import Path

from .wire import encode

SIZE = 2.0
NODES = {"n0": (1.0, 0.0), "n1": (2.0, 1.0), "n2": (1.0, 2.0), "n3": (0.0, 1.0)}
LINKS = list(combinations(NODES, 2))
PATHS_DIR = Path(__file__).parent / "paths"

PERSON_DROP_DB = 8.0   # peak drop when a person stands on the link line
PERSON_WIDTH_M = 0.2   # how fast the drop fades with distance from the line
MOVING_SPEED = 0.05    # m/s above which the camera says "moving"


def zone_of(x: float, y: float) -> int:
    return int(x >= SIZE / 2) + 2 * int(y >= SIZE / 2)


def baseline(a: str, b: str) -> float:
    """Empty-room RSSI in dBm (log-distance path loss)."""
    return -40.0 - 20.0 * math.log10(math.dist(NODES[a], NODES[b]))


def dist_to_link(p, a: str, b: str) -> float:
    """Distance from point p to the segment between nodes a and b."""
    (ax, ay), (bx, by) = NODES[a], NODES[b]
    dx, dy = bx - ax, by - ay
    f = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    f = min(1.0, max(0.0, f))
    return math.dist(p, (ax + f * dx, ay + f * dy))


def drop(p, a: str, b: str, peak_db: float, width_m: float) -> float:
    return peak_db * math.exp(-((dist_to_link(p, a, b) / width_m) ** 2))


def position(waypoints: list, t: float):
    """Person position at time t, or None if nobody is in the room.

    Waypoints are {"t", "x", "y"} sorted by t, linearly interpolated. A
    waypoint with x = null means the person is gone from that time on.
    """
    before = [w for w in waypoints if w["t"] <= t]
    after = [w for w in waypoints if w["t"] > t]
    if not before or before[-1].get("x") is None:
        return None
    a = before[-1]
    if not after or after[0].get("x") is None:
        return (a["x"], a["y"])
    b = after[0]
    f = (t - a["t"]) / (b["t"] - a["t"])
    return (a["x"] + f * (b["x"] - a["x"]), a["y"] + f * (b["y"] - a["y"]))


def is_moving(waypoints: list, t: float, dt: float = 0.2) -> bool:
    now, then = position(waypoints, t), position(waypoints, t - dt)
    return bool(now and then) and math.dist(now, then) / dt > MOVING_SPEED


def simulate(path: dict, rate: float = 15.0, label_rate: float = 5.0,
             seed: int = 0, noise_db: float = 1.0):
    """Yield internal events (see wire.py) for a scripted path, in time order."""
    rng = random.Random(seed)
    waypoints = path.get("person") or []
    objects = path.get("objects") or []
    label_every = max(1, round(rate / label_rate))
    for i in range(int(path["duration_s"] * rate)):
        t = round(i / rate, 3)
        pos = position(waypoints, t)
        moving = is_moving(waypoints, t)
        for a, b in LINKS:
            rssi = baseline(a, b) + rng.gauss(0.0, noise_db)
            for o in objects:  # static: the same drop on every reading
                rssi -= drop((o["x"], o["y"]), a, b,
                             o.get("drop_db", 6.0), o.get("width_m", 0.25))
            if pos:
                d = drop(pos, a, b, PERSON_DROP_DB, PERSON_WIDTH_M)
                if moving:  # a moving body makes the drop flutter
                    d *= max(0.0, 1.0 + rng.gauss(0.0, 0.25))
                rssi -= d
            yield {"kind": "rssi", "t": t, "link": f"{a}-{b}", "rssi": round(rssi)}
        if i % label_every == 0:
            yield {"kind": "label", "t": t,
                   "zone": zone_of(*pos) if pos else None,
                   "present": pos is not None, "moving": moving}


def load_path(name_or_file: str) -> dict:
    """Load a path by file name, or by short name from sim/paths/."""
    p = Path(name_or_file)
    if not p.exists():
        p = PATHS_DIR / f"{name_or_file}.json"
    return json.loads(p.read_text())


def pace(timed_lines, out=sys.stdout, speed: float = 1.0,
         clock=time.monotonic, sleep=time.sleep) -> None:
    """Write (t, line) pairs to `out`, waiting so they arrive at real speed."""
    start, t0 = clock(), None
    for t, line in timed_lines:
        t0 = t if t0 is None else t0
        wait = (t - t0) / speed - (clock() - start)
        if wait > 0:
            sleep(wait)
        out.write(line + "\n")
        out.flush()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path name in sim/paths/ or a path JSON file")
    ap.add_argument("--rate", type=float, default=15.0, help="readings per link per second (10-20)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fast", action="store_true", help="no waiting; use this to record a file")
    args = ap.parse_args(argv)
    events = simulate(load_path(args.path), rate=args.rate, seed=args.seed)
    try:
        if args.fast:
            for e in events:
                print(encode(e))
        else:
            pace((e["t"], encode(e)) for e in events)
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
