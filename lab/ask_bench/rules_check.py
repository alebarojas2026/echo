"""Score the keyword layers alone (no model), on one split. Used to tune them on dev only.

    python -m lab.ask_bench.rules_check --split dev [--misses]
"""
import argparse
from collections import Counter

from . import overlay
from .payloads import load_questions
from .score import decide, judge


def run(split, show=False, layers=("rules_only",)):
    overlay.use()
    from agent import ask as A
    zones, links = A.layout()
    qs = [q for q in load_questions() if q["split"] in split.split(",")]
    ok, bad = Counter(), []
    for g in qs:
        pick, by = decide(g["q"], None, set(layers), zones, links)
        j = judge(g, pick, zones, links)
        ok["tool"] += j["tool_ok"]
        ok["all"] += j["all_ok"]
        if not j["all_ok"]:
            bad.append((g["tool"], j["tool"], pick.get("minutes"), g["minutes"], pick.get("zone"), g["zone"], g["q"]))
    print(f"{split}: {len(qs)} questions, tool {ok['tool'] / len(qs):.1%}, all {ok['all'] / len(qs):.1%}")
    if show:
        for b in sorted(bad):
            print(" ", b)
    return ok, bad


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--misses", action="store_true")
    a = ap.parse_args()
    run(a.split, a.misses)
