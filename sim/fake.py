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
ROUTER_SPOTS = {"S-home": (1.0, 0.0), "S-W30": (0.7, 0.0), "S-E30": (1.3, 0.0)}
PATHS_DIR = Path(__file__).parent / "paths"

REF_DBM = {"wifi": -40.0, "ble": -55.0}  # empty-room level at 1 m
PERSON_DROP_DB = 8.0   # peak drop when a person stands on the link line
PERSON_WIDTH_M = 0.2   # how fast the drop fades with distance from the line
MOVING_SPEED = 0.25    # m/s over 1 s, contract section 6


def link_id(tx: str, rx: str, kind: str) -> str:
    return f"{tx}>{rx}:{kind}"


def zone_of(x: float, y: float) -> int:
    return 1 + int(x >= SIZE / 2) + 2 * int(y < SIZE / 2)


def baseline(tx: str, rx: str, kind: str, nodes: dict = NODES) -> float:
    """Empty-room level in dBm (log-distance path loss)."""
    return REF_DBM[kind] - 20.0 * math.log10(math.dist(nodes[tx], nodes[rx]))


def dist_to_link(p, a, b) -> float:
    """Distance from point p to the segment between points a and b."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    f = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    f = min(1.0, max(0.0, f))
    return math.dist(p, (ax + f * dx, ay + f * dy))


def drop(p, a, b, peak_db: float, width_m: float) -> float:
    return peak_db * math.exp(-((dist_to_link(p, a, b) / width_m) ** 2))


def active(item: dict, t: float) -> bool:
    """True while t is inside the item's optional [t_on, t_off) window."""
    return item.get("t_on", 0.0) <= t < item.get("t_off", math.inf)


def latest(steps: list, t: float, key: str, default):
    """Value of `key` in the last step at or before t (steps are sorted by t)."""
    for step in steps or []:
        if step["t"] <= t:
            default = step[key]
    return default


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
    label_every = max(1, round(rate / label_rate))
    meta = {"session": "sim-" + path.get("name", "path"), "purpose": "demo", "walker": "sim"}
    yield {"type": "meta", "t": 0.0, **meta, **path.get("meta", {})}
    cam_was = None
    for i in range(int(path["duration_s"] * rate)):
        t = round(i / rate, 3)
        pos = position(waypoints, t)
        moving = is_moving(waypoints, t)
        nodes = {**NODES, "pi5": ROUTER_SPOTS[latest(path.get("router"), t, "spot", "S-home")]}
        for tx, rx, kind in LINKS:
            link = link_id(tx, rx, kind)
            if any(active(o, t) and (o.get("link") == link or o.get("node") in (tx, rx))
                   for o in path.get("outages") or []):
                continue  # this link is silent: nothing is sent at all
            dbm = baseline(tx, rx, kind, nodes) + rng.gauss(0.0, noise_db)
            for o in path.get("objects") or []:  # static: the same drop on every reading
                if active(o, t):
                    dbm -= drop((o["x"], o["y"]), nodes[tx], nodes[rx],
                                o.get("drop_db", 6.0), o.get("width_m", 0.25))
            for w in path.get("waves") or []:  # a hand waving in one link's path
                if active(w, t) and w.get("link", "pi5>unoq:wifi") == link:
                    dbm += w.get("amp_db", 4.0) * math.sin(
                        2 * math.pi * w.get("hz", 2.0) * (t - w.get("t_on", 0.0)))
            for j in path.get("jumps") or []:   # a link whose level shifts for no reason in the room
                if active(j, t) and j["link"] == link:
                    dbm += j["db"] + j.get("wobble_db", 0.0) * math.sin(2 * math.pi * 0.4 * (t - j.get("t_on", 0.0)))
            if pos:
                d = drop(pos, nodes[tx], nodes[rx], PERSON_DROP_DB, PERSON_WIDTH_M)
                if moving:  # a moving body makes the drop flutter
                    d *= max(0.0, 1.0 + rng.gauss(0.0, 0.25))
                dbm -= d
            yield {"type": "rssi", "t": t, "link": link,
                   "kind": kind, "tx": tx, "rx": rx, "dbm": round(dbm)}
        cam = latest(path.get("camera"), t, "state", "on")
        if cam == "on" and i % label_every == 0:  # one label per camera frame, empty frames too
            # clipped: the camera sees the person but not their feet, so no zone, foot point or motion
            clipped = bool(pos) and any(active(c, t) for c in path.get("clipped") or [])
            yield {"type": "label", "t": t, "frame": i // label_every,
                   "mode": path.get("label_mode", "person"),
                   "persons_in_frame": int(pos is not None), "present": pos is not None,
                   "zone": None if clipped else zone_of(*pos) if pos else 0,
                   "foot_m": [round(pos[0], 2), round(pos[1], 2)] if pos and not clipped else None,
                   "motion": ("moving" if moving else "still") if pos and not clipped else None,
                   "conf": round(rng.uniform(0.75, 0.95), 2), "clipped": clipped}
        if i % round(rate) == 0 or cam != cam_was:  # camera watch: every second and on any change
            yield {"type": "cam", "t": t, "state": cam,
                   "fps": rate / label_every if cam == "on" else 0.0}
        cam_was = cam


def load_path(name_or_file: str) -> dict:
    """Load a path by file name, or by short name from sim/paths/."""
    p = Path(name_or_file)
    if not p.exists():
        p = PATHS_DIR / f"{name_or_file}.json"
    return json.loads(p.read_text())


def lossy(timed_lines, loss: float, seed: int = 0):
    """Drop a share of already-encoded (t, line) pairs, so seq has gaps like a lossy radio."""
    rng = random.Random(f"loss-{seed}")
    for i, pair in enumerate(timed_lines):
        if i == 0 or rng.random() >= loss:   # the first message (meta) always gets through
            yield pair


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
    ap.add_argument("--loss", type=float, default=0.0, help="share of messages to drop, e.g. 0.05")
    args = ap.parse_args(argv)
    events = simulate(load_path(args.path), rate=args.rate, seed=args.seed)
    encode = encoder(int(time.time() * 1000) if args.start_ms is None else args.start_ms)
    lines = lossy(((e["t"], encode(e)) for e in events), args.loss, args.seed)
    try:
        if args.fast:
            for _, line in lines:
                print(line)
        else:
            pace(lines)
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
