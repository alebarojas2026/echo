"""Fan desk-strip sessions out, on Modal CPUs or on this machine. SIMULATED, dev only.

    modal run lab/desk_modal.py --stage quick              # today's rules, a small batch
    modal run lab/desk_modal.py --stage sweep --n 60       # the whole sweep, 60 seeds per setting
    python -m lab.desk_modal --stage quick --local 8       # the same jobs in 8 local processes

Each stage writes lab/out/desk_<stage>.jsonl (git-ignored), one session per line.
A stage reuses its seeds across settings, so settings are compared on the same
rooms, people and passers-by.

DESK_BRAIN=<folder> runs the brain, advisor and sim code of another checkout
(for example main merged with an open brain PR). The lab code is always this one.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = Path(os.environ.get("DESK_BRAIN") or ROOT).resolve()
OUT = Path(__file__).resolve().parent / "out"
REMOTE = "/root/repo"
RATES = (0, 1, 2, 4, 6, 8, 12)

try:
    import modal
except ImportError:          # local runs don't need it
    modal = None

if modal is not None:
    skip = ["**/__pycache__/**", "tests/**"]
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("numpy==2.5.3", "scipy==1.18.1", "scikit-learn==1.9.1")
        .add_local_dir(BRAIN / "brain", f"{REMOTE}/brain", ignore=skip)
        .add_local_dir(BRAIN / "advisor", f"{REMOTE}/advisor", ignore=skip)
        .add_local_dir(BRAIN / "sim", f"{REMOTE}/sim", ignore=skip)
        .add_local_file(BRAIN / "radio" / "nodes.json", f"{REMOTE}/radio/nodes.json")
        .add_local_dir(ROOT / "lab", f"{REMOTE}/lab", ignore=skip + ["out/**", "figs/**"])
    )
    app = modal.App("radio-sight-desk-twin", image=image)

# What the hall might be like at judging; every session draws its own.
HALL = {"scatter": (0.1, 0.35), "meas_db": (0.3, 0.7), "ble_chan_db": (1.0, 2.5), "drift_db": (0.2, 1.0),
        "coherence_s": (0.5, 2.0), "phone_miss": (0.1, 0.25), "burst_per_min": (0, 3)}


BETTER = {"train_back": False, "train_empty_s": 60.0, "empty_between": True}


def _env(seed):
    import numpy as np
    rng = np.random.default_rng(20_000 + seed)
    return {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in HALL.items()}


def jobs_for(stage: str, n: int = None) -> list:
    J = []

    def add(tag, seed, rate, scene=None, env=None, **kw):
        J.append(dict(tag=tag, seed=seed, env=dict(_env(seed), **(env or {})),
                      scene=dict({"rate": rate}, **(scene or {})), **kw))

    if stage == "quick":                       # today's rules
        for s in range(n or 12):
            for r in (0, 2, 4, 8, 12):
                add("today", 100 + s, r)
    elif stage == "sweep":
        for s in range(n or 80):
            seed = 1000 + s
            for r in RATES:
                # A: tonight's plan as written. B: walkers never labelled behind the arm line,
                # and a 60 s empty recording split in three (BETTER).
                add("A ref", seed, r)
                for links in ("six", "cross", "cross+ends"):
                    add(f"A links {links}", seed, r, links=links)
                add("A train aisle", seed, r, scene={"train_aisle": True})
                add("A train no back", seed, r, scene={"train_back": False})
                add("A train empty split", seed, r, scene={"train_empty_s": 60.0, "empty_between": True})

                def b(tag, scene=None, **kw):
                    add("B " + tag, seed, r, scene=dict(BETTER, **(scene or {})), **kw)
                b("ref")
                for links in ("six", "cross", "cross+ends"):
                    b(f"links {links}", links=links)
                for est in ("mean", "quiet"):
                    b(f"baseline {est}", base_est=est)
                b("baseline open", {"strip_clear_baseline": False})
                for reach in (0.15, 0.25, 0.45):
                    b(f"reach {reach}", {"reach_m": reach})
                for loss in (0.0, 0.3, 0.6):
                    b(f"loss {loss}", {"loss": loss})
                b("train aisle", {"train_aisle": True})
                for nb in (0, 3):
                    b(f"neighbours {nb}", {"neighbours": nb})
                for sc in (0.05, 0.45):
                    b(f"scatter {sc}", env={"scatter": sc})
                for k in (6.0, 18.0):
                    b(f"hall k {k}", {"k_db_desk": k})
                for d in (0.0, 2.0):
                    b(f"drift {d}", env={"drift_db": d})
    elif stage == "visits":                    # every kind of visit on every seed
        for s in range(n or 60):
            for r in (0, 4, 8, 12):
                for v in ("standard", "back40", "two", "backpack", "kid", "lean"):
                    for reach in (0.35, 0.45):
                        add(f"B visit {v} reach {reach}", 3000 + s, r, scene=dict(BETTER, visit=v, reach_m=reach))
                    add(f"A visit {v} reach 0.35", 3000 + s, r, scene={"visit": v})
    elif stage == "today":                     # the brain as it is on main: six links, tonight's place
        for s in range(n or 60):
            for r in RATES:
                add("main six", 1000 + s, r, links="six")
                add("main twelve", 1000 + s, r, links="twelve")
    else:
        raise ValueError(f"unknown stage {stage}")
    return J


def _plain(x):
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if hasattr(x, "item"):
        return x.item()
    return x


def run_jobs(jobs: list) -> list:
    """Run jobs here (in a container, or locally). Errors are kept, not raised."""
    for p in (REMOTE,) if Path(REMOTE).exists() else (str(ROOT), str(BRAIN)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    from lab import desk, rf
    out = []
    for j in jobs:
        t0 = time.perf_counter()
        try:
            r = desk.session(seed=j["seed"], env=rf.Env(**j["env"]), scene=j["scene"],
                             links=j.get("links", "twelve"), base_est=j.get("base_est", "median"))
            r.pop("env", None)
            r["tag"], r["rate"] = j["tag"], j["scene"]["rate"]
        except Exception as e:   # one bad room must not sink the batch
            r = {"tag": j["tag"], "seed": j["seed"], "rate": j["scene"]["rate"], "error": repr(e)}
        r["wall_s"] = round(time.perf_counter() - t0, 2)
        out.append(_plain(r))
    return out


def _write(stage, results, total, suffix=""):
    OUT.mkdir(exist_ok=True)
    path = OUT / f"desk_{stage}{suffix}.jsonl"
    t0, done, errors, cpu_s = time.time(), 0, 0, 0.0
    with path.open("w", encoding="utf-8") as f:
        for rows in results:
            for r in rows:
                f.write(json.dumps(r) + "\n")
                done += 1
                errors += "error" in r
                cpu_s += r.get("wall_s", 0.0)
            if done % 200 < len(rows):
                print(f"{stage}: {done}/{total} sessions, {errors} errors, {time.time() - t0:.0f} s", flush=True)
    usd = cpu_s * (0.0000131 + 1.0 * 0.00000222)   # Modal list prices; an estimate only
    print(f"{stage}: wrote {path} | {done} sessions, {errors} errors | session CPU {cpu_s / 3600:.2f} h | "
          f"about ${usd:.2f} on Modal before container overhead")


if modal is not None:
    CORES = 8

    @app.function(cpu=CORES, memory=6144, timeout=1500, retries=1, max_containers=60)
    def run_batch(jobs: list) -> list:
        """One container works through its jobs in CORES processes."""
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(CORES) as ex:
            return [r for rows in ex.map(run_jobs, [[j] for j in jobs]) for r in rows]

    @app.local_entrypoint()
    def main(stage: str = "quick", n: int = 0, per_call: int = 64, suffix: str = ""):
        jobs = jobs_for(stage, n or None)
        batches = [jobs[i:i + per_call] for i in range(0, len(jobs), per_call)]
        print(f"{stage}: {len(jobs)} sessions in {len(batches)} calls; brain code from {BRAIN}")
        _write(stage, run_batch.map(batches, order_outputs=False), len(jobs), suffix)


if __name__ == "__main__":
    import argparse
    from concurrent.futures import ProcessPoolExecutor
    ap = argparse.ArgumentParser(description="Desk-strip sessions on this machine (SIMULATED).")
    ap.add_argument("--stage", default="quick")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--local", type=int, default=4, help="processes")
    ap.add_argument("--suffix", default="")
    a = ap.parse_args()
    jobs = jobs_for(a.stage, a.n or None)
    with ProcessPoolExecutor(a.local) as ex:
        _write(a.stage, ex.map(run_jobs, [[j] for j in jobs]), len(jobs), a.suffix)
