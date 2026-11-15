"""One-spot judging days (simulated): false "someone is here", missed step-ons, intrusion vs passed-by.

    python lab/soak/spot.py lab/soak/farm-runs/r4 --tree lab/soak/farm-trees/r4/kit

Reads the days lab/soak/day.py wrote on a one-spot layout: segments.jsonl (every path played, with the
judge's waypoints and the passers-by), presence.jsonl (each change of pred.present) and events.jsonl.
The truth is rebuilt from the paths with the tree's own sim (sim.fake, sim.layout), so --tree must be
the tree the days ran on. Simulated: rank, never quote.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

STEP = 0.1


def lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
    except OSError:
        return


def passer_at(p, t):
    if not p["t_on"] <= t < p["t_off"]:
        return None
    f = (t - p["t_on"]) / (p["t_off"] - p["t_on"])
    return (p["x0"] + f * (p["x1"] - p["x0"]), p["y"])


def truth(segs, fake, layout):
    """[(t, judge inside the spot)] every 0.1 s, and the passers as absolute intervals."""
    out, passers, last = [], [], False
    for s in segs:
        person = s.get("person") or []
        n = int((s["end"] - s["start"]) / STEP)
        for i in range(n):
            t = i * STEP
            p = fake.position(person, min(t, s.get("dur", t)))
            last = bool(p) and layout.zone_of(*p) != 0
            out.append((s["start"] + t, last))
        for q in s.get("passer_list") or []:
            passers.append({"on": s["start"] + q["t_on"], "off": s["start"] + q["t_off"], "cut": q.get("cut", False),
                            "y": q["y"], "armed": None})
    return out, passers


def day(folder, fake, layout):
    segs = [s for s in lines(folder / "segments.jsonl") if "person" in s]
    if not segs:
        return None
    tl, passers = truth(segs, fake, layout)
    pres = list(lines(folder / "presence.jsonl"))
    events = list(lines(folder / "events.jsonl"))
    cfg = next(lines(folder / "config.jsonl"), {}).get("cfg", {})

    def present_at(t):
        v = None
        for r in pres:
            if r["t"] > t:
                break
            v = r["present"]
        return v

    def inside_between(a, b):
        return any(x for t, x in tl if a <= t <= b)

    def near(t, pad=2.0):
        found = [q for q in passers if q["on"] - pad <= t <= q["off"] + pad]
        if any(q["cut"] for q in found):
            return "cut-through"
        if found:
            d = min(abs(q["y"] + 0.2) for q in found)
            return "passer <0.25 m from Pi B" if d < 0.25 else "passer >=0.25 m from Pi B"
        return "nobody near"

    empty_s = sum(STEP for t, x in tl if not x and present_at(t) is not None)
    false_on = defaultdict(int)
    for r in pres:
        if r["present"] is True and not inside_between(r["t"] - 2.0, r["t"] + 0.5):
            false_on[near(r["t"])] += 1
    # step-ons: runs of "inside" at least 3 s long
    runs, start = [], None
    for t, x in tl:
        if x and start is None:
            start = t
        if not x and start is not None:
            if t - start >= 3:
                runs.append((start, t))
            start = None
    missed = known = 0
    for a, b in runs:
        states = [present_at(a)] + [r["present"] for r in pres if a <= r["t"] <= b + 1]
        if all(s is None for s in states):
            continue   # no decision all through (blind, a baseline, no model yet): not a miss
        known += 1
        missed += not any(s is True for s in states)
    intr = defaultdict(int)
    for e in events:
        if e["kind"] == "intrusion":
            intr["judge stepped on" if inside_between(e["t"] - 6, e["t"] + 0.5) else near(e["t"], 3)] += 1
    cuts_armed = 0
    armed_on = [(r["t"], r["armed"]) for r in pres]
    for q in passers:
        if q["cut"]:
            a = [v for t, v in armed_on if t <= q["on"]]
            cuts_armed += bool(a and a[-1])
    return {"day": folder.name, "passers_per_min": cfg.get("passers_per_min"), "empty_h": empty_s / 3600,
            "false_on": dict(false_on), "step_ons": known, "missed": missed, "intrusions": dict(intr),
            "passers": len(passers), "cuts": sum(q["cut"] for q in passers), "cuts_while_armed": cuts_armed}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root")
    ap.add_argument("--tree", required=True, help="the farm tree the days ran on (for sim/ and radio/nodes.json)")
    ap.add_argument("--match", default="", help="only day folders whose name contains this")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.tree).resolve()))
    from sim import fake
    from sim.layout import LAYOUT
    rows = [r for f in sorted(Path(a.root).iterdir()) if f.is_dir() and a.match in f.name
            for r in [day(f, fake, LAYOUT)] if r]
    tot = defaultdict(float)
    for r in rows:
        print(json.dumps(r))
        tot["empty_h"] += r["empty_h"]
        tot["step_ons"] += r["step_ons"]
        tot["missed"] += r["missed"]
        for k, v in r["false_on"].items():
            tot["false_on " + k] += v
        for k, v in r["intrusions"].items():
            tot["intrusion " + k] += v
        tot["cuts_while_armed"] += r["cuts_while_armed"]
    print(json.dumps({k: round(v, 2) for k, v in tot.items()}))
    if tot["empty_h"]:
        print(json.dumps({"false_on_per_empty_hour": {k[9:]: round(v / tot["empty_h"], 1) for k, v in tot.items()
                                                       if k.startswith("false_on ")}}))


if __name__ == "__main__":
    main()
