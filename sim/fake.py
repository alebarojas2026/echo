"""Fake Radio Sight data: RSSI for every link plus matching camera messages.

    python -m sim.fake zone_tour            # real time, JSON lines on stdout
    python -m sim.fake zone_tour --fast > data/sessions/tour.jsonl

Room, nodes, links and zones follow CONTRACTS.md section 3. Metres, origin at
the south-west corner, x east, y north.

    y=2 +----unoq----+      zones:  1 | 2      0 = empty
        |  1  |  2   |              --+--
      west----+----east             3 | 4
        |  3  |  4   |
    y=0 +----pi5-----+
       x=0          x=2

Each diagonal link crosses exactly one zone. The two pi5>unoq links (wifi and
ble) run up the middle.
"""
import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from .wire import encoder

SIZE = 2.0
NODES = {"unoq": (1.0, 2.0), "pi5": (1.0, 0.0), "east": (2.0, 1.0), "west": (0.0, 1.0)}
LINKS = [("pi5", "unoq", "wifi"), ("pi5", "unoq", "ble"), ("east", "unoq", "ble"),
         ("west", "unoq", "ble"), ("east", "pi5", "ble"), ("west", "pi5", "ble")]  # (tx, rx, kind)
PATHS_DIR = Path(__file__).parent / "paths"

REF_DBM = {"wifi": -40.0, "ble": -55.0}  # empty-room level at 1 m
PERSON_DROP_DB = 8.0   # peak drop when a person stands on the link line
PERSON_WIDTH_M = 0.2   # how fast the drop fades with distance from the line
MOVING_SPEED = 0.25    # m/s over 1 s, contract section 6


def link_id(tx: str, rx: str, kind: str) -> str:
    return f"{tx}>{rx}:{kind}"


def zone_of(x: float, y: float) -> int:
    return 1 + int(x >= SIZE / 2) + 2 * int(y < SIZE / 2)


def baseline(tx: str, rx: str, kind: str) -> float:
    """Empty-room level in dBm (log-distance path loss)."""
    return REF_DBM[kind] - 20.0 * math.log10(math.dist(NODES[tx], NODES[rx]))


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


def is_moving(waypoints: list, t: float, window_s: float = 1.0) -> bool:
    """Foot speed over the last second (or since they appeared) above MOVING_SPEED."""
    now = position(waypoints, t)
    if not now:
        return False
    for k in range(10, 0, -1):  # oldest position inside the window
        dt = window_s * k / 10
        then = position(waypoints, t - dt)
        if then:
            return math.dist(now, then) / dt > MOVING_SPEED
    ahead = position(waypoints, t + 0.1)  # first instant in the room: look ahead
    return bool(ahead) and math.dist(now, ahead) / 0.1 > MOVING_SPEED


def simulate(path: dict, rate: float = 15.0, label_rate: float = 7.5,
             seed: int = 0, noise_db: float = 1.0):
    """Yield internal events (see wire.py) for a scripted path, in time order."""
    rng = random.Random(seed)
    waypoints = path.get("person") or []
    objects = path.get("objects") or []
    label_every = max(1, round(rate / label_rate))
    meta = {"session": "sim-" + path.get("name", "path"), "purpose": "demo", "walker": "sim"}
    yield {"type": "meta", "t": 0.0, **meta, **path.get("meta", {})}
    for i in range(int(path["duration_s"] * rate)):
        t = round(i / rate, 3)
        pos = position(waypoints, t)
        moving = is_moving(waypoints, t)
        for tx, rx, kind in LINKS:
            dbm = baseline(tx, rx, kind) + rng.gauss(0.0, noise_db)
            for o in objects:  # static: the same drop on every reading
                dbm -= drop((o["x"], o["y"]), tx, rx,
                            o.get("drop_db", 6.0), o.get("width_m", 0.25))
            if pos:
                d = drop(pos, tx, rx, PERSON_DROP_DB, PERSON_WIDTH_M)
                if moving:  # a moving body makes the drop flutter
                    d *= max(0.0, 1.0 + rng.gauss(0.0, 0.25))
                dbm -= d
            yield {"type": "rssi", "t": t, "link": link_id(tx, rx, kind),
                   "kind": kind, "tx": tx, "rx": rx, "dbm": round(dbm)}
        if i % label_every == 0:  # one label per camera frame, empty frames too
            yield {"type": "label", "t": t, "frame": i // label_every,
                   "mode": path.get("label_mode", "person"),
                   "persons_in_frame": int(pos is not None), "present": pos is not None,
                   "zone": zone_of(*pos) if pos else 0,
                   "foot_m": [round(pos[0], 2), round(pos[1], 2)] if pos else None,
                   "motion": ("moving" if moving else "still") if pos else None,
                   "conf": round(rng.uniform(0.75, 0.95), 2), "clipped": False}
        if i % round(rate) == 0:  # camera watch: once a second
            yield {"type": "cam", "t": t, "state": "on", "fps": rate / label_every}


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
    ap.add_argument("--start-ms", type=int, default=None, help="epoch ms of the first message (default: now)")
    args = ap.parse_args(argv)
    events = simulate(load_path(args.path), rate=args.rate, seed=args.seed)
    encode = encoder(int(time.time() * 1000) if args.start_ms is None else args.start_ms)
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
