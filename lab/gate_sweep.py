"""Try many settings of the one-spot presence rules on the tuning recordings, on Modal CPUs.

    modal run lab/gate_sweep.py --sessions <folder> --plan <plan.json> --out <folder> --grid presence
    modal run lab/gate_sweep.py --sessions <folder> --plan <plan.json> --out <folder> --grid motion \
        --fixed '{"on_db": 8, "off_db": 4}'

Every variant is lab/gate_tune.py's replay: the recordings through brain.core.Brain with that
variant's numbers. Only the sessions the plan marks "tune" are read and sent; a held-out
session never leaves this PC from here (lab.gate_tune.load does the choosing, and has a test).
The recordings must be scrubbed first (python -m sim.scrub, then --check).

The cloud is for choosing numbers at a desk, before the demo. Nothing here runs on the board
and the board never talks to it: what goes on the board is a few plain numbers in the layout
file, put there by a person in a PR.

Writes <out>/<grid>.jsonl, one line per variant (its numbers and its total). It picks nothing
and writes no PROOF.md: lab/gate_pick.py reads the file and shows the safe region.
"""
from __future__ import annotations

import gzip
import itertools
import json
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 48             # variants per container call (fewer when the grid is small, so it still spreads out)
TIMEOUT_S = 1500       # a call is CHUNK replays of a few seconds each; this is the stop for one that hangs
CONTAINERS = 100

GRIDS = {
    # on and off levels (dB under the empty level), the median's window, decisions in a row before
    # enter / exit is said, and how fast the empty level follows drift (0 = it does not)
    "presence": {"on_db": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16], "off_db": [1, 2, 3, 4, 5, 6, 7, 8],
                 "window_ms": [300, 500, 700, 1000, 1500, 2000], "zone_hold": [3, 5, 8, 10],
                 "drift_follow_s": [0, 10, 30, 60, 120]},
    # where the line's spread reads as moving, and over how long the spread is taken
    "motion": {"moving_spread_db": [0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5, 4.0],
               "spread_ms": [1000, 1500, 2000, 2500, 3000]},
}


def variants(grid: str, fixed: dict) -> list:
    axes = GRIDS[grid]
    out = []
    for values in itertools.product(*axes.values()):
        v = {**fixed, **dict(zip(axes, values))}
        if v.get("off_db", 0) < v.get("on_db", 99) and v.get("window_ms", 0) <= v.get("spread_ms", 2000):
            out.append(v)
    return out


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("numpy", "scikit-learn")
         .add_local_dir(ROOT / "brain", "/root/brain", ignore=["tests", "__pycache__"])
         .add_local_dir(ROOT / "advisor", "/root/advisor", ignore=["tests", "__pycache__"])
         .add_local_dir(ROOT / "radio", "/root/radio", ignore=["tests", "__pycache__"])
         .add_local_dir(ROOT / "lab", "/root/lab", ignore=["soak", "tests", "__pycache__"]))
app = modal.App("gate-sweep", image=image)


@app.function(cpu=1, memory=1024, timeout=TIMEOUT_S, max_containers=CONTAINERS, retries=1)
def replay_chunk(packed: bytes, chunk: list) -> list:
    import warnings

    from lab import gate_tune

    warnings.simplefilter("ignore")
    runs = json.loads(gzip.decompress(packed))
    for run in runs:
        run["base"] = [tuple(r) for r in run["base"]]
        run["readings"] = [tuple(r) for r in run["readings"]]
    out = []
    for params in chunk:
        got = gate_tune.run_variant(runs, params)
        out.append({"params": got["params"], "total": got["total"], "base_moved_db": got["base_moved_db"]})
    return out


@app.local_entrypoint()
def main(sessions: str, plan: str, out: str, grid: str = "presence", fixed: str = "{}", limit: int = 0):
    from lab import gate_tune

    runs = gate_tune.load(sessions, json.loads(Path(plan).read_text(encoding="utf-8")), "tune")
    for run in runs:   # only the lines the run's layout has
        known = {k["id"] for k in json.loads((gate_tune.LAYOUTS / f'{run["layout"]}.json').read_text())["links"]}
        run["base"] = [r for r in run["base"] if r[1] in known]
        run["readings"] = [r for r in run["readings"] if r[1] in known]
    packed = gzip.compress(json.dumps(runs).encode())
    todo = variants(grid, json.loads(fixed))
    if limit:
        todo = todo[:limit]
    size = max(1, min(CHUNK, -(-len(todo) // 10)))
    chunks = [todo[i:i + size] for i in range(0, len(todo), size)]
    print(f"{len(todo)} variants in {len(chunks)} calls; {len(packed) / 1e6:.2f} MB of tuning readings each "
          f"({sum(1 for r in runs for p in r['parts'] if p['scored'])} scored sessions, no held-out ones)")
    t0, rows = time.time(), []
    for part in replay_chunk.map([packed] * len(chunks), chunks):
        rows += part
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{grid}.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"{len(rows)} variants back in {time.time() - t0:.0f} s -> {folder / (grid + '.jsonl')}")
