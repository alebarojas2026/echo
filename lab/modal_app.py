"""Fan simulated sessions out on Modal CPUs. SIMULATED, dev only.

    python -m lab.overlay fetch                         # pinned brain PR files, once
    modal run lab/modal_app.py --stage smoke            # 20 sessions, checks the image
    modal run lab/modal_app.py --stage env --n 600      # the environment sweep
    modal run lab/modal_app.py --stage forest           # also: nominal, window, protocol, person

Each stage writes lab/out/<stage>.jsonl (git-ignored), one session per line.
Stages reuse seeds across levels, so levels are compared on the same rooms.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"
REMOTE = "/root/repo"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("numpy==2.5.3", "scipy==1.18.1", "scikit-learn==1.9.1")
    .add_local_dir(ROOT / "brain", f"{REMOTE}/brain", ignore=["**/__pycache__/**", "tests/**"])
    .add_local_dir(ROOT / "advisor", f"{REMOTE}/advisor", ignore=["**/__pycache__/**", "tests/**"])
    .add_local_dir(ROOT / "sim", f"{REMOTE}/sim", ignore=["**/__pycache__/**", "tests/**"])
    .add_local_file(ROOT / "radio" / "nodes.json", f"{REMOTE}/radio/nodes.json")
    .add_local_dir(ROOT / "lab", f"{REMOTE}/lab", ignore=["**/__pycache__/**", "out/**", "tests/**"])
)
app = modal.App("radio-sight-lab", image=image)

# Ranges the environment sweep draws from (uniform). "moderate" is a plausible
# demo hall; "wide" goes well past it to find where things break.
WIDE = {
    "k_db": (3, 25), "coherence_s": (0.3, 3.0), "meas_db": (0.2, 1.0), "ble_chan_db": (0.5, 4.0),
    "drift_db": (0.1, 3.0), "scatter": (0.05, 0.45), "bystanders": (0, 4), "wifi_frame_hz": (8, 80),
    "phone_hz": (4, 11), "phone_miss": (0.05, 0.5), "burst_per_min": (0, 8), "burst_s": (0.2, 2.0),
    "throttle_per_min": (0, 0.5), "hand_db": (2, 6), "cam_fps": (5, 10), "cam_miss": (0, 0.2),
    "foot_noise_m": (0.02, 0.15), "cam_latency_ms": (50, 300),
}
MODERATE = {
    "k_db": (12, 20), "coherence_s": (0.5, 2.0), "meas_db": (0.3, 0.7), "ble_chan_db": (1.0, 2.5),
    "drift_db": (0.2, 1.0), "scatter": (0.1, 0.3), "bystanders": (0, 2), "wifi_frame_hz": (20, 60),
    "phone_hz": (7, 10), "phone_miss": (0.1, 0.25), "burst_per_min": (0, 3), "burst_s": (0.3, 1.0),
    "hand_db": (3, 5), "foot_noise_m": (0.03, 0.08), "cam_latency_ms": (80, 200),
}


def _env(seed, ranges, fixed=None):
    import numpy as np
    rng = np.random.default_rng(10_000 + seed)
    env = {k: float(rng.uniform(lo, hi)) for k, (lo, hi) in ranges.items()}
    if "bystanders" in env:
        env["bystanders"] = int(round(env["bystanders"]))
    env.update(fixed or {})
    return env


def jobs_for(stage: str, n: int = None) -> list:
    """The list of session jobs for a stage."""
    J = []

    def add(tag, seed, ranges=MODERATE, **kw):
        J.append(dict(tag=tag, seed=seed, env=_env(seed, ranges, kw.pop("env", None)), **kw))

    if stage == "smoke":
        for s in range(n or 20):
            add("nominal", s, ranges={})
    elif stage == "nominal":
        for s in range(n or 200):
            add("nominal", 1000 + s, ranges={})
    elif stage == "env":
        for s in range(n or 600):
            add("wide", 2000 + s, ranges=WIDE)
    elif stage == "forest":
        for s in range(n or 40):
            for ne in (10, 30, 60, 120):
                for md in (6, 12, None):
                    add(f"forest n{ne} d{md}", 3000 + s, cfg={"n_estimators": ne, "max_depth": md}, replays=False)
    elif stage == "window":
        for s in range(n or 60):
            for w in (500, 750, 1000, 1500, 2000):
                add(f"window {w}", 4000 + s, cfg={"window_ms": w}, replays=False)
    elif stage == "protocol":
        for s in range(n or 40):
            for v in (1.0, 3.0, 5.0, 10.0):
                add(f"train_still_s {v}", 5000 + s, proto={"train_still_s": v}, replays=False)
            for v in (0.05, 0.12, 0.25, 0.4):
                add(f"spot_jitter_m {v}", 5000 + s, proto={"spot_jitter_m": v}, replays=False)
            for v in (1, 2, 3, 5):
                add(f"train_walkers {v}", 5000 + s, proto={"train_walkers": v}, replays=False)
            for v in (0.2, 0.35, 0.5, 0.65, 0.8):
                add(f"wave_dist_m {v}", 5000 + s, proto={"wave_dist_m": v})
            for v in (0.0, 0.05, 0.1, 0.2):
                add(f"tray_jitter_m {v}", 5000 + s, proto={"tray_jitter_m": v}, replays=False)
            for v in (0.3, 0.6, 1.0):
                add(f"cam_view_m {v}", 5000 + s, env={"cam_view_m": v}, replays=False)
    elif stage == "alertfix":
        for s in range(n or 100):
            for v in (5.0, 10.0):
                add(f"train_still_s {v}", 7000 + s, ranges={}, proto={"train_still_s": v}, replays=["alert", "xray"])
    elif stage == "person":
        for s in range(n or 40):
            for v in (0.4, 0.7, 1.0, 1.3, 1.6):
                add(f"speed {v}", 6000 + s, live_person={"speed": v}, replays=False)
            for v in (1.1, 1.3, 1.5, 1.75, 1.95):
                add(f"height {v}", 6000 + s, live_person={"height_m": v}, replays=False)
            for v in (3.0, 6.0, 9.0, 12.0):
                add(f"depth {v}", 6000 + s, live_person={"depth_db": v}, replays=False)
    else:
        raise ValueError(f"unknown stage {stage}")
    return J


def _plain(x):
    """JSON-ready: numpy scalars and tuples become plain values."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if hasattr(x, "item"):
        return x.item()
    return x


def run_jobs(jobs: list) -> list:
    """Run jobs here (in a container, or locally). Errors are kept, not raised."""
    if REMOTE not in sys.path and Path(REMOTE).exists():
        sys.path.insert(0, REMOTE)
    from lab import rf, run
    out = []
    for j in jobs:
        t0 = time.perf_counter()
        try:
            r = run.session(seed=j["seed"], env=rf.Env(**j["env"]), cfg=j.get("cfg"),
                            live_person=j.get("live_person"), proto=j.get("proto"),
                            replays=j.get("replays", True))
            r["tag"] = j["tag"]
        except Exception as e:   # one bad room must not sink the batch
            r = {"tag": j["tag"], "seed": j["seed"], "error": repr(e)}
        r["wall_s"] = round(time.perf_counter() - t0, 2)
        out.append(_plain(r))
    return out


@app.function(cpu=1.0, memory=1024, timeout=1800, retries=1)
def run_batch(jobs: list) -> list:
    return run_jobs(jobs)


@app.local_entrypoint()
def main(stage: str = "smoke", n: int = 0, per_call: int = 4):
    jobs = jobs_for(stage, n or None)
    batches = [jobs[i:i + per_call] for i in range(0, len(jobs), per_call)]
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{stage}.jsonl"
    t0, done, errors, cpu_s = time.time(), 0, 0, 0.0
    with path.open("w", encoding="utf-8") as f:
        for rows in run_batch.map(batches, order_outputs=False):
            for r in rows:
                f.write(json.dumps(r) + "\n")
                done += 1
                errors += "error" in r
                cpu_s += r.get("wall_s", 0.0)
            print(f"{stage}: {done}/{len(jobs)} sessions, {errors} errors, {time.time() - t0:.0f} s")
    # Modal list prices (CPU per core-second, memory per GiB-second); an estimate only.
    usd = cpu_s * (0.0000131 + 1.0 * 0.00000222)
    print(f"{stage}: wrote {path} | session CPU {cpu_s / 3600:.2f} h | about ${usd:.2f} before container overhead")
