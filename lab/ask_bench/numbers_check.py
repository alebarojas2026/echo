"""Check the rule "a number never appears in an answer unless it is in a returned row".

    python -m lab.ask_bench.numbers_check [--stores 40]

Fills many random stores (random states and events in the desk layout, odd floats, missing
values, advice text with numbers in it), runs every tool with many arguments, and counts answers
with a number that is in no returned row. It reports two ways: strictly (rows only), and the way
#474's test does (rows, plus the minutes that were asked for). No model is involved.
"""
import argparse
import json
import random
import re
from collections import Counter

from . import overlay

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(value) -> set:
    if isinstance(value, dict):
        return set().union(*map(numbers_in, value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*map(numbers_in, value)) if value else set()
    return set(NUMBER.findall(str(value)))


def random_store(seed: int, links: list, now_ms: int):
    from store import Store
    rng = random.Random(seed)
    s = Store(":memory:")
    t = now_ms - rng.randint(60, 7200) * 1000
    seq, zone, still = 0, 1, 0.0
    advice = None
    while t < now_ms:
        seq += 1
        r = rng.random()
        if r < 0.1:
            pred = None
        elif r < 0.4:
            pred = {"present": False, "kind": "none", "zone": 0, "motion": None, "still_s": 0}
        else:
            if rng.random() < 0.05:
                zone = 3 - zone
            motion = rng.choice(["moving", "still", "still"])
            still = still + 1 if motion == "still" else 0.0
            pred = {"present": True, "kind": rng.choice(["person"] * 5 + ["object"]), "zone": zone,
                    "motion": motion, "still_s": round(still + rng.random(), rng.choice([0, 1, 3]))}
        if rng.random() < 0.01:
            advice = {"text": f"Move the router {rng.choice([20, 30, 45])} cm west.", "link": "pi5>unoq:wifi",
                      "to_spot": "S-W30", "before_dbm": round(-70 - 10 * rng.random(), rng.choice([0, 1, 2])),
                      "after_dbm": rng.choice([None, round(-55 - 10 * rng.random(), 1)])}
        state = {"v": 2, "type": "state", "t": t, "seq": seq, "src": rng.choice(["sim", "live"]),
                 "links": [{"id": l, "dbm": rng.choice([None, round(-40 - 50 * rng.random(), rng.choice([0, 1, 4]))]),
                            "drop_db": round(5 * rng.random(), 2), "status": "ok"} for l in links if rng.random() < 0.9],
                 "health": {"status": "ok", "blind": rng.sample(links, rng.choice([0, 0, 0, 1]))},
                 "pred": pred, "alert": {"state": rng.choice(["none", "counting", "check_on"]), "zone": zone},
                 "armed": rng.random() < 0.3, "advice": advice,
                 "model": rng.choice([None, {"trained": False},
                                      {"trained": True, "ver": f"m{rng.randint(1, 12)}", "windows": rng.randint(50, 900),
                                       "train_sessions": ["s01", "s07"][: rng.randint(0, 2)],
                                       "train_s": rng.choice([None, round(3 + 9 * rng.random(), 2)]),
                                       "ms_per_decision": rng.choice([None, round(2 + 3 * rng.random(), 3)])}])}
        s.add(state)
        if rng.random() < 0.02:
            kind = rng.choice(["alert_on", "alert_off", "checkin", "armed", "disarmed", "intrusion", "intrusion"])
            info = {"zone": rng.choice([1, 2])} if kind in ("alert_on", "alert_off") else {}
            if kind == "intrusion":
                info = rng.choice([{"zone": rng.choice([1, 2])}, {"link": rng.choice(links)}])
            if kind == "checkin":
                info = {"link": "pi5>unoq:wifi"}
            s.add({"type": "event", "t": t + rng.randint(0, 999), "kind": kind, "id": f"e{seq}", "src": "sim", "info": info})
        t += 1000 + rng.choice([0, 0, 0, 0, 1000, 2500])
    return s


def run(n_stores: int = 40, seed: int = 1):
    overlay.use()
    from agent import ask as A
    from agent.tools import TOOLS
    zones, links = A.layout()
    now = 1_763_149_500_000
    strict, loose, total = Counter(), Counter(), Counter()
    examples = {}
    for k in range(n_stores):
        store = random_store(seed * 1000 + k, links, now)
        for name, tool in TOOLS.items():
            for minutes in (1, 2, 5, 10, 60, 1440):
                for zone in (None, 1, 2):
                    for link in (None, links[0], links[7]):
                        out = tool(store, now, zones, minutes=minutes, zone=zone, link=link)
                        total[name] += 1
                        extra = numbers_in(out["answer"]) - numbers_in(out["rows"])
                        if extra:
                            strict[name] += 1
                            examples.setdefault(("strict", name), (out["answer"], sorted(extra)))
                        if extra - {str(minutes)}:
                            loose[name] += 1
                            examples.setdefault(("loose", name), (out["answer"], sorted(extra - {str(minutes)})))
    return total, strict, loose, examples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", type=int, default=40)
    a = ap.parse_args()
    total, strict, loose, ex = run(a.stores)
    for name in total:
        print(f"{name:15s} answers {total[name]:6d}  number in no row: {strict[name]:6d}  "
              f"not even the asked minutes: {loose[name]:5d}")
    for k, v in ex.items():
        print(k, json.dumps(v)[:300])
