"""Times the brain's hot path on sim data: features, predict, health, alert, X-ray, advisor.

    python board/bench/bench_brain.py                  # 10 Hz for 60 s, from the repo root
    python board/bench/bench_brain.py --trees 30 --depth 10 --hz 5

Trains the real model on sim sessions, then plays a 60 s sim feed (a zone tour, then the tray
at T1) in real time through the calls the live loop (brain/core.py) makes, timed one by one,
plus the advisor, which the live loop doesn't call yet. predict is per window (the contract's
ms_per_decision), every other step per tick. Ctrl-C or SIGTERM ends it early.
"""
import argparse
import json
import os
import platform
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import sklearn

from advisor.advise import advise
from brain import features as F, train as T
from brain.alert import Watch
from brain.health import Health
from brain.xray import Xray
from sim import fake, wire

T0_MS = 1_763_149_500_000
STEPS = ("ingest", "predict", "health", "alert", "xray", "advisor", "state_json")
# The tray at T1, wherever radio/nodes.json puts that spot (sim/layout.py turns the spot into metres).
FEED = fake.LAYOUT.resolve(dict(fake.load_path("zone_tour"), name="bench", duration_s=60,
                                objects=[{"spot": "T1", "drop_db": 10, "t_on": 32}]))


def sim(path, seed, mode=None):
    """A sim path as bus messages, with recv_t stamped the way the bus does it."""
    path = dict(fake.load_path(path) if isinstance(path, str) else path, **({"label_mode": mode} if mode else {}))
    encode = wire.encoder(T0_MS)
    msgs = [json.loads(encode(ev)) for ev in fake.simulate(path, seed=seed)]
    return [dict(m, recv_t=m["t"]) for m in msgs]


def train(base, walkers=3):
    """The real model, trained on the kinds of sessions the board records."""
    def session(name, path, seed, mode=None, walker=None):
        return {"meta": {"session": name, "walker": walker, "purpose": mode or "train"},
                "messages": sim(path, seed, mode)}
    sessions = [session("empty", "empty_room", 10), session("metal", "metal_object", 11, "object"),
                session("tray", "tray_t1", 12, "object")]
    for i in range(walkers):
        sessions += [session(f"tour{i}", "zone_tour", 20 + i, walker=f"w{i}"),
                     session(f"still{i}", "stand_still", 30 + i, walker=f"w{i}")]
    return T.Model(base).fit(sessions)


def feed(seconds):
    """FEED as the datagrams the brain reads, looped (each lap 60 s later) to cover `seconds`."""
    lap, lap_ms = sim(FEED, seed=7), FEED["duration_s"] * 1000
    laps = range(int(seconds * 1000 // lap_ms) + 1)
    return iter([json.dumps(dict(m, recv_t=m["recv_t"] + k * lap_ms)) for k in laps for m in lap])


def run(seconds=60.0, hz=10.0, trees=None, depth=None, walkers=3, fast=False, out=print):
    T.FOREST = dict(T.FOREST, **{k: v for k, v in (("n_estimators", trees), ("max_depth", depth)) if v})
    nodes = json.loads((REPO / "radio" / "nodes.json").read_text())
    empty = sim("empty_room", seed=99)   # 30 s with nobody in the room: the baseline
    model = train(base := F.baseline(empty), walkers)
    mhz = Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    out(f"bench_brain: {platform.machine()} ({platform.system()}), {os.cpu_count()} cores"
        f"{f', {int(mhz.read_text()) // 1000} MHz max' if mhz.exists() else ''}, "
        f"Python {platform.python_version()}, scikit-learn {sklearn.__version__}")
    out(f"model: 3 forests x {T.FOREST['n_estimators']} trees, depth {T.FOREST['max_depth']}, "
        f"{model.windows} windows, trained in {model.train_s:.1f} s (one-off, not the hot path)")
    hm = Health.from_nodes(nodes, base_dbm=base)
    hm.set_expected({k: sum(m.get("link") == k for m in empty) / 30.0 for k in base})
    xr, win, msgs = Xray.from_nodes(nodes), F.Windower(base), feed(seconds)
    watch = Watch({z["id"]: z.get("still_alert_s") for z in nodes["zones"]})   # no LED grid
    times = {s: [] for s in STEPS + ("tick",)}
    seen = dict.fromkeys(("pred", "blind", "objects", "advice"), 0)
    raw, pending, stop, n = None, None, [], int(seconds * hz)
    old_term = signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    out(f"running {n} ticks at {hz:g} Hz ({seconds:g} s){', not paced' if fast else ''}")
    cpu0, wall0 = time.process_time(), time.perf_counter()
    next_t = wall0
    try:
        for k in range(n):
            if stop:
                break
            now = T0_MS + round((k + 1) * 1000 / hz)
            t, new = [time.perf_counter()], []
            while True:   # ingest: decode and window every message since the last tick
                pending = pending or json.loads(next(msgs))
                if pending["recv_t"] > now:
                    break
                new += win.push(pending)
                if pending["type"] == "rssi":
                    link, t_ms, dbm = pending["link"], pending["recv_t"], pending["dbm"]
                    xr.add(link, t_ms, base[link] - dbm)
                    hm.add(link, t_ms, dbm)
                    watch.on_rssi(pending)
                pending = None
            t.append(time.perf_counter())
            for w in new:   # like brain/core.py: predict every new 0.1 s window, whatever the rate
                p0 = time.perf_counter()
                raw = model.predict(w)
                times["predict"].append((time.perf_counter() - p0) * 1000)   # per window
            t.append(time.perf_counter())
            health = hm.update(now, raw and raw["kind"])
            pred = None if hm.blind else raw
            t.append(time.perf_counter())
            watch.on_pred(now, pred)
            t.append(time.perf_counter())
            xo = xr.update(now, pred and pred["kind"])
            t.append(time.perf_counter())
            advice = advise(xo["xray"], health["links"], nodes, xo["objects"])
            t.append(time.perf_counter())
            json.dumps({"v": 2, "type": "state", "t": now, "seq": k, "src": "sim",
                        "links": health["links"], "health": health["health"], "pred": pred,
                        "objects": xo["objects"], "xray": xo["xray"], "advice": advice})
            t.append(time.perf_counter())
            for step, a, b in zip(STEPS, t, t[1:]):
                if step != "predict":
                    times[step].append((b - a) * 1000)
            times["tick"].append((t[-1] - t[0]) * 1000)
            for key, hit in zip(seen, (pred, hm.blind, xo["objects"], advice)):
                seen[key] += bool(hit)
            if not fast:   # never sprint to catch up after a slow tick
                next_t = max(next_t + 1 / hz, time.perf_counter() - 1 / hz)
                time.sleep(max(0.0, next_t - time.perf_counter()))
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, old_term)
    wall = time.perf_counter() - wall0
    res = {"ticks": len(times["tick"]), "hz": hz, "seconds": wall, **seen,
           "steps": {s: _stats(v) for s, v in times.items()},
           "cpu_pct": 100.0 * (time.process_time() - cpu0) / wall,
           "over_budget": sum(v > 1000 / hz for v in times["tick"])}
    _report(res, out)
    return res


def _stats(ms):
    a = np.asarray(ms or [0.0])
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "max": float(a.max())}


def _report(res, out):
    out(f"{'step':<12}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}")
    for step, s in res["steps"].items():
        out(f"{step.replace('tick', 'tick (all)'):<12}{s['p50']:>9.2f}{s['p95']:>9.2f}{s['max']:>9.2f}")
    out(f"CPU: {res['cpu_pct']:.1f}% of one core ({res['cpu_pct'] / os.cpu_count():.1f}% of all "
        f"{os.cpu_count()}) over {res['seconds']:.1f} s")
    out(f"ticks: {res['ticks']}, over the {1000 / res['hz']:.0f} ms budget: {res['over_budget']}; "
        f"with pred {res['pred']}, blind {res['blind']}, objects {res['objects']}, advice {res['advice']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--hz", type=float, default=10.0, help="state messages a second")
    ap.add_argument("--trees", type=int, help="trees per forest (FOREST in brain/train.py)")
    ap.add_argument("--depth", type=int, help="max tree depth")
    ap.add_argument("--fast", action="store_true", help="no pacing, for tests")
    a = ap.parse_args(argv)
    run(a.seconds, a.hz, a.trees, a.depth, fast=a.fast, out=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
