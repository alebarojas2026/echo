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

from .layout import LAYOUT
from .wire import encoder

# From radio/nodes.json (sim/layout.py), so the fake data follows the layout the real code reads.
SIZE = LAYOUT.size_m[0]
NODES = dict(LAYOUT.nodes)            # id -> (x, y)
LINKS = list(LAYOUT.links)            # (tx, rx, kind)
ROUTER_SPOTS = dict(LAYOUT.router_spots)
PATHS_DIR = Path(__file__).parent / "paths"

REF_DBM = {"wifi": -40.0, "ble": -55.0}  # empty-room level at 1 m
PERSON_DROP_DB = 8.0   # peak drop when a person stands on the link line
PRESENCE_DROP_DB = 18.0   # ... on the line the layout says decides presence (measured on the kit: 15 to 21 dB)
PERSON_WIDTH_M = LAYOUT.width_m   # how fast the drop fades with distance from the line (sim/layout.py)
PERSON_BODY_M = LAYOUT.body_m     # the full drop within this distance of the line
MOVING_SPEED = 0.25    # m/s over 1 s, contract section 6
# People outside the area (a path's "passers" and "neighbours"). A body walking near a link also
# shakes it a little without standing on it (multipath): a guess for the fake feed, not measured.
SCATTER_DB, SCATTER_M = 2.0, 0.5   # rms shake next to a link, and how fast it fades with distance
ARM_DROP_DB, ARM_WIDTH_M = 2.0, 0.1   # an arm tip reaching over the edge blocks a little
PASS_FROM_M = 1.5      # passers-by start and finish this far past the ends

# Optional hall links (issue #358): far beacons heard a few times a second, at uneven moments.
HALL_SENT_HZ = 25.0                # adverts a second a hall beacon sends
HALL_HEARD = 0.3                   # the share of them a receiver hears
HALL_CHANNEL_DB = (-1.5, 0.0, 1.0) # an advert is heard on one of three channels, each at its own level
HALL_NOISE_DB = 0.7


def link_id(tx: str, rx: str, kind: str) -> str:
    return f"{tx}>{rx}:{kind}"


def zone_of(x: float, y: float) -> int:
    return LAYOUT.zone_of(x, y)


def baseline(tx: str, rx: str, kind: str, nodes: dict = None) -> float:
    """Empty-room level in dBm (log-distance path loss)."""
    nodes = NODES if nodes is None else nodes
    return REF_DBM[kind] - 20.0 * math.log10(math.dist(nodes[tx], nodes[rx]))


def dist_to_link(p, a, b) -> float:
    """Distance from point p to the segment between points a and b."""
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    f = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    f = min(1.0, max(0.0, f))
    return math.dist(p, (ax + f * dx, ay + f * dy))


def drop(p, a, b, peak_db: float, width_m: float, body_m: float = 0.0) -> float:
    return peak_db * math.exp(-((max(0.0, dist_to_link(p, a, b) - body_m) / width_m) ** 2))


def person_drop(p, a, b) -> float:
    """What a person standing at p takes off the link from a to b, before any flutter."""
    return drop(p, a, b, PERSON_DROP_DB, PERSON_WIDTH_M, PERSON_BODY_M)


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


def receivers() -> list:
    """The nodes that receive, in the order LINKS first names them."""
    return list(dict.fromkeys(rx for _, rx, _ in LINKS))


def hall_links(path: dict) -> list:
    """(tx, rx) of every hall link of a path: each hall beacon heard by each receiver. [] with no "hall"."""
    beacons = (path.get("hall") or {}).get("beacons") or {}
    return [(tx, rx) for rx in receivers() for tx in beacons]


def hall_walk(walk: dict, tx: str, rx: str, t: float) -> bool:
    """True while somebody walks along this hall link. A walk with no "tx" or "rx" is on all of them."""
    return active(walk, t) and walk.get("tx", tx) == tx and walk.get("rx", rx) == rx


def hall_events(path: dict, seed: int = 0) -> list:
    """rssi events of the path's hall links, in time order. They use their own random stream, so a
    path gives the same core readings with and without a "hall" block.

    Each beacon sends about `sent_hz` adverts a second and a receiver hears a share `heard` of them,
    on one of three channels that sit at different levels. During a walk the level dips (deepest in
    the middle of the walk) and flutters. Outages silence a hall beacon like any other node.
    """
    hall = path.get("hall") or {}
    rng = random.Random(f"hall-{seed}")
    every, heard = 1.0 / hall.get("sent_hz", HALL_SENT_HZ), hall.get("heard", HALL_HEARD)
    out = []
    for tx, rx in hall_links(path):
        link, t = link_id(tx, rx, "ble"), rng.uniform(0.0, every)
        while t < path["duration_s"]:
            silent = any(active(o, t) and (o.get("link") == link or o.get("node") in (tx, rx))
                         for o in path.get("outages") or [])
            if not silent and rng.random() < heard:
                spot = ROUTER_SPOTS[latest(path.get("router"), t, "spot", "S-home")] if rx == "pi5" else NODES[rx]
                dbm = (REF_DBM["ble"] - 20.0 * math.log10(math.dist(hall["beacons"][tx], spot))
                       + rng.choice(HALL_CHANNEL_DB) + rng.gauss(0.0, HALL_NOISE_DB))
                for w in hall.get("walks") or []:
                    if hall_walk(w, tx, rx, t):
                        mid, half = (w["t_on"] + w["t_off"]) / 2, (w["t_off"] - w["t_on"]) / 2
                        dbm -= (w.get("drop_db", PERSON_DROP_DB) * max(0.0, 1.0 - abs(t - mid) / half)
                                * max(0.0, 1.0 + rng.gauss(0.0, 0.3)))
                out.append({"type": "rssi", "t": round(t, 3), "link": link, "kind": "ble",
                            "tx": tx, "rx": rx, "dbm": round(dbm)})
            t += every + rng.uniform(0.0, 0.010)
    return sorted(out, key=lambda e: e["t"])


def bystanders(path: dict, t: float) -> list:
    """People outside the area at time t, as [(x, y, moving, arm)]: arm is the (x, y) of an arm tip
    reaching towards the area, or None.

    "passers": [{"t_on", "from": "west" | "east", "lane_m", "speed_mps", "reach_m"}] walk past on
    the aisle side (y < 0), lane_m from the edge, from PASS_FROM_M past one end to as far past the
    other; reach_m > lane_m puts an arm tip over the edge while their feet stay outside.
    "neighbours": [{"end": "west" | "east", "past_m", "t_on", "t_off"}] stand still beyond an end,
    level with the middle of the area."""
    w, h = LAYOUT.strip_m or LAYOUT.size_m
    out = []
    for p in path.get("passers") or []:
        walked = (t - p["t_on"]) * p.get("speed_mps", 1.0)
        if not 0 <= walked <= w + 2 * PASS_FROM_M:
            continue
        x = -PASS_FROM_M + walked if p.get("from", "west") == "west" else w + PASS_FROM_M - walked
        y = -p.get("lane_m", 0.3)
        reach = p.get("reach_m", 0.0)
        out.append((x, y, True, (x, y + reach) if reach else None))
    for n in path.get("neighbours") or []:
        if active(n, t):
            past = n.get("past_m", 1.0)
            out.append((-past if n.get("end") == "west" else w + past, h / 2, False, None))
    return out


def simulate(path: dict, rate: float = 15.0, label_rate: float = 7.5,
             seed: int = 0, noise_db: float = 1.0):
    """Yield internal events (see wire.py) for a scripted path, in time order."""
    rng = random.Random(seed)
    hall, h = hall_events(path, seed), 0
    aisle = random.Random(f"aisle-{seed}")   # its own draws, so a path without bystanders is unchanged
    waypoints = path.get("person") or []
    label_every = max(1, round(rate / label_rate))
    meta = {"session": "sim-" + path.get("name", "path"), "purpose": "demo", "walker": "sim"}
    yield {"type": "meta", "t": 0.0, **meta, **path.get("meta", {})}
    cam_was = None
    # "teacher": "desk" = the webcam on the desk (teacher/DESK.md): no foot point, and no usable
    # label within dead_band_m of the line between left and right.
    desk, split = path.get("teacher") == "desk", LAYOUT.split_x_m if LAYOUT.strip_m else SIZE / 2
    band = 0.0 if split is None else path.get("dead_band_m", 0.0)   # one spot has no line between sides
    for i in range(int(path["duration_s"] * rate)):
        t = round(i / rate, 3)
        while h < len(hall) and hall[h]["t"] <= t:   # hall readings come at their own uneven moments
            yield hall[h]
            h += 1
        pos = position(waypoints, t)
        moving = is_moving(waypoints, t)
        nodes = {**NODES, "pi5": ROUTER_SPOTS[latest(path.get("router"), t, "spot", "S-home")]}
        others = bystanders(path, t)
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
                d = person_drop(pos, nodes[tx], nodes[rx])
                if link == LAYOUT.presence_line:
                    d *= PRESENCE_DROP_DB / PERSON_DROP_DB
                if moving:  # a moving body makes the drop flutter
                    d *= max(0.0, 1.0 + rng.gauss(0.0, 0.25))
                dbm -= d
            for x, y, walking, arm in others:   # someone outside: blocks only if close, shakes when walking
                d = person_drop((x, y), nodes[tx], nodes[rx])
                if walking:
                    d *= max(0.0, 1.0 + aisle.gauss(0.0, 0.25))
                    d -= aisle.gauss(0.0, SCATTER_DB * math.exp(-((dist_to_link((x, y), nodes[tx], nodes[rx]) / SCATTER_M) ** 2)))
                if arm:
                    d += drop(arm, nodes[tx], nodes[rx], ARM_DROP_DB, ARM_WIDTH_M)
                dbm -= d
            yield {"type": "rssi", "t": t, "link": link,
                   "kind": kind, "tx": tx, "rx": rx, "dbm": round(dbm)}
        cam = latest(path.get("camera"), t, "state", "on")
        if cam == "on" and i % label_every == 0:  # one label per camera frame, empty frames too
            # clipped: the camera sees the person but not their feet, so no zone, foot point or motion
            inside = bool(pos) and zone_of(*pos) != 0   # section 4: present only with a foot point inside the area
            clipped = inside and (any(active(c, t) for c in path.get("clipped") or [])
                                  or (desk and band > 0 and abs(pos[0] - split) < band))
            yield {"type": "label", "t": t, "frame": i // label_every,
                   "mode": path.get("label_mode", "person"),
                   "persons_in_frame": int(pos is not None) + len(others), "present": inside,
                   "zone": None if clipped else zone_of(*pos) if inside else 0,
                   "foot_m": [round(pos[0], 2), round(pos[1], 2)] if inside and not clipped and not desk else None,
                   "motion": ("moving" if moving else "still") if inside and not clipped else None,
                   "conf": round(rng.uniform(0.75, 0.95), 2), "clipped": clipped}
        if i % round(rate) == 0 or cam != cam_was:  # camera watch: every second and on any change
            yield {"type": "cam", "t": t, "state": cam,
                   "fps": rate / label_every if cam == "on" else 0.0}
        cam_was = cam


def load_path(name_or_file: str) -> dict:
    """Load a path by file name, or by short name from sim/paths/. "lesson" is built from the
    layout (sim/lesson.py), not read from a file."""
    if name_or_file == "lesson":
        from . import lesson
        return lesson.path()
    p = Path(name_or_file)
    if not p.exists():
        p = PATHS_DIR / f"{name_or_file}.json"
    return LAYOUT.resolve(json.loads(p.read_text()))   # zone-relative points become metres for this layout


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
