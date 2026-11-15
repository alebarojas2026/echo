"""Simulated recordings for the sweep's dry run. SIMULATED, dev only.

    python -m lab.sweep_sim sweep-sim/ --nodes radio/nodes.json

Writes a folder shaped like the board's data/sessions: one <session>.jsonl per recording (a meta
line, then rssi and label messages with recv_t, as the bus writes them), baselines.jsonl and
baseline.json, and the nodes.json they were made on. The readings come from sim/fake.py's link
model, run on the layout given, with three things it doesn't do on its own:
- each walker has their own body (how deep and how wide their shadow is);
- each desk has its own per-link offsets (antenna angle, a beacon set down again), with its own
  20 s baseline, so features taken against the baseline can be compared with absolute ones;
- some readings are lost.
Every message says src "sim", so the sweep labels everything from here "simulated".
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from contextlib import contextmanager
from pathlib import Path

from sim import fake
from sim.layout import Layout
from sim.wire import encoder

T0_MS = 1_763_200_000_000

# (session, purpose, walker, desk). Ten train sessions (eight walks by four people over two desks,
# and the empty strip at each desk) and two held-out walks by people never in training.
PLAN = [
    ("a-w1", "train", "w1", 0), ("a-w2", "train", "w2", 0), ("a-w3", "train", "w3", 0),
    ("a-w4", "train", "w4", 0), ("a-empty", "train", None, 0), ("a-held", "heldout", "w5", 0),
    ("b-w1", "train", "w1", 1), ("b-w2", "train", "w2", 1), ("b-w3", "train", "w3", 1),
    ("b-w4", "train", "w4", 1), ("b-empty", "train", None, 1), ("b-held", "heldout", "w6", 1),
]


@contextmanager
def on_layout(layout: Layout, drop_db: float = fake.PERSON_DROP_DB, width_m: float = fake.PERSON_WIDTH_M):
    """Run sim/fake.py on this layout and body (it reads these module values on every reading)."""
    names = ("LAYOUT", "NODES", "LINKS", "ROUTER_SPOTS", "SIZE", "PERSON_DROP_DB", "PERSON_WIDTH_M")
    old = {k: getattr(fake, k) for k in names}
    fake.LAYOUT, fake.NODES, fake.LINKS = layout, dict(layout.nodes), list(layout.links)
    fake.ROUTER_SPOTS, fake.SIZE = dict(layout.router_spots), layout.size_m[0]
    fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M = drop_db, width_m
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(fake, k, v)


def walk(layout: Layout, rng: random.Random, still_s: float = 10.0) -> dict:
    """A training walk like the live lesson: step in, stand left, stand right, wander, stand still, leave."""
    w, h = layout.strip_m or layout.size_m
    aisle = -0.4 if layout.strip_m else 0.05
    zones = sorted(layout.centres)

    def spot(z):
        cx, cy = layout.centres[z]
        return [round(min(w - 0.05, max(0.05, cx + rng.uniform(-0.15, 0.15))), 2),
                round(min(h - 0.05, max(0.05, cy + rng.uniform(-0.15, 0.15))), 2)]

    pts, t = [], 1.0
    x0 = rng.uniform(0.2, w - 0.2)
    pts.append({"t": 0.0, "x": round(x0, 2), "y": aisle})

    def go(p, move_s, stay_s):
        nonlocal t
        t += move_s
        pts.append({"t": round(t, 2), "x": p[0], "y": p[1]})
        t += stay_s
        pts.append({"t": round(t, 2), "x": p[0], "y": p[1]})

    for z in zones:                       # every zone once, the way the lesson asks
        go(spot(z), rng.uniform(1.2, 2.0), rng.uniform(5.0, 7.0))
    for _ in range(3):
        for _ in range(4):                # wandering with short pauses
            go(spot(rng.choice(zones)), rng.uniform(0.8, 1.6), rng.uniform(0.0, 1.5))
        go(spot(rng.choice(zones)), rng.uniform(1.0, 1.5), still_s * rng.uniform(0.6, 1.0))   # a still stand
    go([round(rng.uniform(0.2, w - 0.2), 2), aisle], rng.uniform(1.0, 1.5), 0.0)
    pts.append({"t": round(t + 0.1, 2), "x": None})
    return {"name": "walk", "duration_s": round(t + 4.0, 1), "person": pts, "objects": []}


def empty(seconds: float) -> dict:
    return {"name": "empty", "duration_s": seconds, "person": [], "objects": []}


def _messages(layout, path, seed, start_ms, offsets, body, loss, noise_db):
    rng = random.Random(f"msg-{seed}")
    encode = encoder(start_ms, src="sim")
    with on_layout(layout, *body):
        events = list(fake.simulate(path, rate=15.0, seed=seed, noise_db=noise_db))
    out = []
    for e in events:
        if e["type"] == "meta":
            continue
        if e["type"] == "rssi":
            if rng.random() < loss:
                continue
            e = dict(e, dbm=round(e["dbm"] + offsets[e["link"]]))
        msg = json.loads(encode(e))
        msg["recv_t"] = msg["t"] + rng.randint(1, 6)
        out.append(msg)
    return sorted(out, key=lambda m: m["recv_t"])


def make(folder, nodes_path, plan=PLAN, seed: int = 0, loss: float = 0.08, noise_db: float = 1.5) -> Path:
    """Write the simulated sessions folder. Returns it."""
    from brain.features import baseline
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    doc = json.loads(Path(nodes_path).read_text(encoding="utf-8"))
    layout = Layout(doc)
    shutil.copyfile(nodes_path, folder / "nodes.json")
    rng = random.Random(seed)
    link_ids = [fake.link_id(*lk) for lk in layout.links]
    bodies = {}
    desk_offsets = {}
    t_ms = T0_MS
    base_log, last_desk = [], None
    for i, (sid, purpose, walker, desk) in enumerate(plan):
        if desk not in desk_offsets:
            desk_offsets[desk] = {l: rng.gauss(0.0, 3.0) for l in link_ids}
        if desk != last_desk:   # set the layout down: a 20 s baseline of the empty strip
            msgs = _messages(layout, empty(20.0), seed * 1000 + 900 + desk, t_ms, desk_offsets[desk],
                             (fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M), loss, noise_db)
            base = {k: float(v) for k, v in baseline(msgs).items()}
            t_ms = msgs[-1]["recv_t"] + 5_000
            base_log.append({"t": t_ms - 4_000, "base": base})
            last_desk = desk
        if walker and walker not in bodies:
            bodies[walker] = (rng.uniform(4.0, 10.0), rng.uniform(0.15, 0.3))
        path = walk(layout, rng, still_s=rng.uniform(8.0, 14.0)) if walker else empty(30.0)
        body = bodies.get(walker, (fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M))
        msgs = _messages(layout, path, seed * 1000 + i, t_ms + 50, desk_offsets[desk], body, loss, noise_db)
        meta = {"v": 2, "type": "meta", "t": t_ms, "seq": 1, "src": "sim", "session": sid,
                "purpose": purpose, "walker": walker, "recv_t": t_ms + 2}
        with open(folder / f"{sid}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            for m in [meta] + msgs:
                f.write(json.dumps(m, separators=(",", ":")) + "\n")
        t_ms = msgs[-1]["recv_t"] + 10_000
    with open(folder / "baselines.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for e in base_log:
            f.write(json.dumps(e) + "\n")
    last = base_log[-1]
    (folder / "baseline.json").write_text(json.dumps(
        {"t": last["t"], "session": None, "links": {k: {"base_dbm": v, "expected_hz": 13.8}
                                                    for k, v in last["base"].items()}}, indent=1) + "\n")
    return folder


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--nodes", default=str(Path(__file__).resolve().parent.parent / "radio" / "nodes.json"))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    out = make(args.folder, args.nodes, seed=args.seed)
    print(f"wrote {len(PLAN)} simulated sessions to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
