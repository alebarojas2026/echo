"""Sweep the brain's settings over the recordings, on Modal CPUs, with a sealed held-out score.

    modal run lab/sweep.py --sessions data/sessions/keep --scrubbed
    modal run lab/sweep.py --sessions sweep-sim                # simulated sessions (python -m lab.sweep_sim)
    modal run lab/sweep.py --sessions sweep-sim --quick        # a small grid, to check the image

Results go to sweep-out/<timestamp>/ (git-ignored). See lab/SWEEP.md.

Only the train and object recordings go up for tuning. The held-out recordings stay on this PC
until a winner is picked, then go up once, to one call that scores the winner and today's
defaults. The containers run the repo's own brain code; no model trained here goes to the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/root/repo"
sys.path.insert(0, REMOTE if Path(REMOTE).exists() else str(ROOT))

CPU = 2.0
JOBS_PER_CALL = 2        # model settings per container call: more calls, shorter ones
IGNORE = ["**/__pycache__/**", "tests/**"]

image = (
    modal.Image.debian_slim(python_version="3.13")      # the board's Python
    .pip_install("numpy==2.5.3", "scipy==1.18.1", "scikit-learn==1.9.1")
    .add_local_dir(ROOT / "brain", f"{REMOTE}/brain", ignore=IGNORE)
    .add_local_dir(ROOT / "advisor", f"{REMOTE}/advisor", ignore=IGNORE)
    .add_local_dir(ROOT / "sim", f"{REMOTE}/sim", ignore=IGNORE + ["paths/**"])
    .add_local_dir(ROOT / "proof", f"{REMOTE}/proof", ignore=IGNORE + ["*.md"])
    .add_local_dir(ROOT / "lab", f"{REMOTE}/lab", ignore=IGNORE + ["out/**", "*.md"])
    .add_local_file(ROOT / "radio" / "nodes.json", f"{REMOTE}/radio/nodes.json")
)
app = modal.App("deadzone-sweep", image=image)

QUICK = {"window_ms": [1000], "features": ["absolute", "relative"], "forest": [[60, 12]],
         "links": ["all", "router_receiver"], "lesson_s": [None, 30], "smooth": [[10, 6]],
         "moving_run": [5], "unsure_p": [0.0, 0.55]}


@app.function(cpu=CPU, memory=2048, timeout=600, max_containers=300)
def run_jobs(jobs: list, store=None, posts=None) -> list:
    import time
    t0 = time.monotonic()
    from lab import sweep_core as C
    blob = store["train"]
    out = [C.run_job(blob, j, posts, n_jobs=int(CPU), lesson_curve=j["lesson_s"] is None) for j in jobs]
    for res in out:   # the whole call, start-up and unpacking included, goes into the cost
        res["seconds"] = (time.monotonic() - t0) / len(out)
    return out


@app.function(cpu=CPU, memory=2048, timeout=600)
def score_heldout(train_blob: bytes, sealed_blob: bytes, settings: list) -> list:
    from lab import sweep_core as C
    return C.score_heldout(train_blob, sealed_blob, settings, n_jobs=int(CPU))


@app.local_entrypoint()
def main(sessions: str, scrubbed: bool = False, nodes: str = "", quick: bool = False, ledger: str = ""):
    import time
    from lab import sweep_core as C
    from lab import sweep_report as R

    t0 = time.monotonic()
    with modal.Dict.ephemeral() as store:
        def map_jobs(blob, jobs, posts):
            store["train"] = blob       # tuning sessions only; sealed ones never go in here
            calls = [jobs[i:i + JOBS_PER_CALL] for i in range(0, len(jobs), JOBS_PER_CALL)]
            print(f"{len(jobs)} model settings x {len(posts)} post settings = {len(jobs) * len(posts)} variants, "
                  f"{len(calls)} containers")
            out = []
            for res in run_jobs.map(calls, kwargs={"store": store, "posts": posts}, return_exceptions=True):
                if isinstance(res, Exception):
                    print(f"a call failed and is left out: {res}")
                    continue
                out += res
            return out

        def held(train_blob, sealed_blob, settings):
            return score_heldout.remote(train_blob, sealed_blob, settings)

        rep = R.run(sessions, map_jobs, held, scrubbed=scrubbed, nodes=nodes or None,
                    ledger_path=ledger or None, grid=QUICK if quick else None, cpu=CPU)
    print()
    if rep.get("refused"):
        print(rep["refused"])
        for i, t in enumerate(rep.get("record_next") or [], 1):
            print(f"  {i}. {t}")
        print(f"written: {rep['folder']}/summary.md")
        sys.exit(2)
    print(Path(rep["folder"], "summary.md").read_text(encoding="utf-8"))
    print(f"written: {rep['folder']}  ({time.monotonic() - t0:.0f} s)")
