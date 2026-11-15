"""The two long hall paths with a hall that is busy all the time. SIMULATED, dev only.

    python -m lab.hall --local 8            # writes lab/out/hall.jsonl
    python -m lab.hall --seed 2 --people 100

"Movement on this path" (brain/hall.py, PR #389 @ 3342c40) compares a link's
spread with its own quiet level, the 20th percentile of the last 5 minutes.
The question here: with 0 to 300 people in the hall, some of them always
walking, does that flag still mean anything, and what would make it honest?

One session is 12 minutes of one hall link, 12 or 20 m long, at torso height:
  - `people` in a 20 x 20 m hall around it; a share of them walk (random legs,
    0.6-1.4 m/s, with pauses), the rest stand or sit and sway;
  - one scripted walker who crosses the path every 45 s (the "somebody walked
    through" a judge would be shown);
  - lab/rf.py's physics for every body near the path (shadow and a reflected
    ray), three advertising channels, missed adverts, whole-dBm readings.
The readings go through the real rule. Three ways to set the quiet level are
compared on the same readings:
  own      the rule as it is: the link's own last 5 minutes;
  empty    a quiet level measured once on the empty hall and kept;
  honest   as "empty", but the path is reported as busy (no single mover can be
           told apart) while its 20th-percentile spread sits above twice the
           empty hall's.
Scored: how often the flag is on, how often it is on when the scripted walker
crosses (hit) and in 4 s windows when they are far away (false).

Trust: how often bodies cross a path this long, and what a self-set threshold
does with that. Not: the dB of one crossing 10 m from both ends, or the hall's
real tiers (a path over people's heads sees far less).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import types
from pathlib import Path

import numpy as np

from lab import rf

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / ".overlay" / "brain_hall.py"
PIN = {"path": "brain/hall.py", "pr": 389, "commit": "3342c40cee37a1a0585626f1cb6180e41b1ccd70"}
DT = 0.05
HALL_M = 20.0
T_S = 720.0
CROSS_EVERY_S = 45.0


def rule():
    """brain.hall: from the tree if it is there, else the pinned PR file (cached in lab/.overlay/)."""
    try:
        from brain import hall
        return hall
    except ImportError:
        pass
    if "brain.hall" in sys.modules:
        return sys.modules["brain.hall"]
    if not CACHE.exists():
        CACHE.parent.mkdir(exist_ok=True)
        show = ["git", "show", f"{PIN['commit']}:{PIN['path']}"]
        try:
            src = subprocess.run(show, cwd=ROOT, check=True, capture_output=True, text=True).stdout
        except subprocess.CalledProcessError:
            subprocess.run(["git", "fetch", "-q", "origin", f"pull/{PIN['pr']}/head"], cwd=ROOT, check=True)
            src = subprocess.run(show, cwd=ROOT, check=True, capture_output=True, text=True).stdout
        CACHE.write_text(src, encoding="utf-8")
    mod = types.ModuleType("brain.hall")
    mod.__file__ = str(CACHE)
    sys.modules["brain.hall"] = mod
    exec(compile(CACHE.read_text(encoding="utf-8"), str(CACHE), "exec"), mod.__dict__)
    return mod


def _walker(rng, n):
    """Random legs across the hall with pauses: x, y every DT."""
    x, y = np.empty(n), np.empty(n)
    k, p = 0, rng.uniform(0, HALL_M, 2)
    while k < n:
        q = rng.uniform(0, HALL_M, 2)
        v = rng.uniform(0.6, 1.4)
        m = max(2, int(np.linalg.norm(q - p) / v / DT))
        s = np.linspace(0, 1, m)[: n - k]
        x[k:k + len(s)], y[k:k + len(s)] = p[0] + s * (q[0] - p[0]), p[1] + s * (q[1] - p[1])
        k += len(s)
        p = q
        m = min(int(rng.exponential(4.0) / DT), n - k)      # stops to look at a project
        x[k:k + m], y[k:k + m] = p[0], p[1]
        k += m
    return x, y


def _stander(rng, n):
    p = rng.uniform(0, HALL_M, 2)
    a = math.exp(-DT / 2.0)
    from scipy.signal import lfilter
    sw = lfilter([1.0], [1.0, -a], rng.normal(0, rng.uniform(0.01, 0.03) * math.sqrt(1 - a * a), (n, 2)), axis=0)
    return p[0] + sw[:, 0], p[1] + sw[:, 1]


def simulate(seed, people, walk_share, length_m, scatter=0.2):
    """(t_ms, dbm) readings of one hall link, and the scripted walker's crossing times (s)."""
    rng = np.random.default_rng(seed)
    n = int(T_S / DT)
    a, b = (HALL_M / 2 - length_m / 2, HALL_M / 2), (HALL_M / 2 + length_m / 2, HALL_M / 2)
    lam = rf.LAMBDA_M["ble"]
    bodies = []
    for k in range(int(people)):
        xy = _walker(rng, n) if rng.random() < walk_share else _stander(rng, n)
        bodies.append((xy, rf.Person.draw(rng)))
    # the scripted walker: straight across the path every CROSS_EVERY_S, otherwise far away
    crossings = np.arange(60.0, T_S - 10, CROSS_EVERY_S)
    sx, sy = np.full(n, np.nan), np.full(n, np.nan)
    for tc in crossings:
        xc = rng.uniform(a[0] + 2.0, b[0] - 2.0)
        v = rng.uniform(0.8, 1.3)
        i0, i1 = int((tc - 4.0 / v) / DT), int((tc + 4.0 / v) / DT)
        s = (np.arange(i0, i1) * DT - tc) * v
        sx[i0:i1], sy[i0:i1] = xc, HALL_M / 2 + s * rng.choice([-1, 1])
    # readings
    hz, miss = 8.5, rng.uniform(0.15, 0.4)
    adv = np.cumsum(1 / hz + rng.uniform(0, 0.01, int(T_S * hz * 1.2)))
    adv = adv[(adv < T_S) & (rng.random(len(adv)) >= miss)]
    i = np.clip((adv / DT).astype(int), 0, n - 1)
    loss = np.zeros(len(adv))
    field = np.zeros(len(adv), complex)
    for (x, y), p in bodies:
        loss += rf.shadow_db(x[i], y[i], a, b, lam, p.width_m, p.depth_db, p.height_m)
        field += rf.scatter_field(x[i], y[i], a, b, lam, scatter, rng.uniform(0, 6.3))
    me = rf.Person.draw(rng)
    loss += rf.shadow_db(sx[i], sy[i], a, b, lam, me.width_m, me.depth_db, me.height_m)
    field += rf.scatter_field(sx[i], sy[i], a, b, lam, scatter, rng.uniform(0, 6.3))
    dif = rf._ar1_complex(rng, int(T_S / 0.05) + 2, 0.05, 1.0)[np.clip((adv / 0.05).astype(int), 0, None)]
    E = 10 ** (-loss / 20) + field + dif / math.sqrt(10 ** (20 / 10))
    dbm = -62.0 - 22 * math.log10(length_m) + 20 * np.log10(np.maximum(np.abs(E), 1e-3))
    dbm += rng.normal(0, 1.5, 3)[rng.integers(0, 3, len(adv))] + rng.normal(0, 0.5, len(adv))
    return (adv * 1000).astype(int), np.round(dbm), crossings


def replay(t_ms, dbm, quiet_fixed=None):
    """The rule's row every 100 ms. quiet_fixed: use this quiet level instead of the link's own."""
    H = rule()
    link = H._Link("h>unoq:ble", "h", "unoq", None)
    saved = H.quiet_db
    if quiet_fixed is not None:
        H.quiet_db = lambda samples: quiet_fixed if len(samples) >= H.QUIET_MIN_SAMPLES else None
    out, k = [], 0
    try:
        for now in range(0, int(T_S * 1000), 100):
            while k < len(t_ms) and t_ms[k] <= now:
                link.add(int(t_ms[k]), float(dbm[k]))
                k += 1
            row = link.row(now)
            own = saved(link.samples)
            out.append((now / 1000, row["moving"], row["activity"], own))
    finally:
        H.quiet_db = saved
    return out


def _score(rows, crossings, busy=None):
    t = np.array([r[0] for r in rows])
    on = np.array([r[1] for r in rows])
    if busy is not None:
        on = on & ~busy
    live = t >= 330.0                                   # after the first 5 minutes of quiet-level history
    hits = [bool(on[(t >= c - 2) & (t <= c + 2)].any()) for c in crossings if c >= 330]
    far = [c + CROSS_EVERY_S / 2 for c in crossings if 330 <= c + CROSS_EVERY_S / 2 < T_S - 5]
    false = [bool(on[(t >= c - 2) & (t <= c + 2)].any()) for c in far]
    flips = int(np.sum(np.diff(on[live].astype(int)) == 1))
    return {"on_frac": round(float(on[live].mean()), 3), "hit": round(float(np.mean(hits)), 3),
            "false": round(float(np.mean(false)), 3), "starts_per_min": round(flips / ((T_S - 330) / 60), 2)}


def session(seed=0, people=100, walk_share=0.25, length_m=15.0, scatter=0.2):
    t0 = time.perf_counter()
    H = rule()
    t_e, d_e, _ = simulate(seed + 500_000, 0, 0.0, length_m, scatter)         # the same link, empty hall
    empty = replay(t_e, d_e)
    q_empty = max(H.QUIET_FLOOR_DB, float(np.percentile([r[3] for r in empty if r[3] is not None], 50)))
    t_ms, dbm, crossings = simulate(seed, people, walk_share, length_m, scatter)
    own = replay(t_ms, dbm)
    fixed = replay(t_ms, dbm, quiet_fixed=q_empty)
    q_now = np.array([r[3] if r[3] is not None else np.nan for r in own])
    busy = np.nan_to_num(q_now, nan=0.0) > 2.0 * q_empty
    live = np.array([r[0] for r in own]) >= 330.0
    return {"seed": seed, "people": people, "walk_share": walk_share, "length_m": length_m,
            "quiet_empty_db": round(q_empty, 2), "quiet_own_db": round(float(np.nanmedian(q_now[live])), 2),
            "busy_frac": round(float(busy[live].mean()), 3),
            "own": _score(own, crossings), "empty": _score(fixed, crossings),
            "honest": _score(fixed, crossings, busy=busy),
            "wall_s": round(time.perf_counter() - t0, 2)}


def _job(a):
    try:
        return session(*a)
    except Exception as e:
        return {"seed": a[0], "people": a[1], "error": repr(e)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hall paths in a busy hall (SIMULATED).")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--people", type=int, default=100)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--local", type=int, default=4)
    a = ap.parse_args(argv)
    if a.seed is not None:
        print(json.dumps(session(a.seed, a.people), indent=1))
        return
    from concurrent.futures import ProcessPoolExecutor
    jobs = [(s, n, w, d) for s in range(a.n) for n in (0, 1, 3, 10, 30, 100, 200, 300)
            for w in (0.1, 0.25) for d in (12.0, 20.0)]
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    with ProcessPoolExecutor(a.local) as ex, (out / "hall.jsonl").open("w", encoding="utf-8") as f:
        for k, r in enumerate(ex.map(_job, jobs, chunksize=4)):
            f.write(json.dumps(r) + "\n")
            if k % 200 == 0:
                print(f"hall: {k}/{len(jobs)}", flush=True)
    print("hall: wrote", out / "hall.jsonl")


if __name__ == "__main__":
    main()
