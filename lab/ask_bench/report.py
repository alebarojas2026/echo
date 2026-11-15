"""The numbers for the write-up: main combos on all and on held-out questions, repeat-run
agreement, and the worst misses of one combo on held-out questions.

    python -m lab.ask_bench.report --tag final [--best rules_new] [--repeats final-r1,final-t4]
"""
import argparse
import json
from collections import Counter

from .questions import OUT
from .score import evaluate, misses, print_table

MAIN = ["rules474", "pr474", "pr474+args10", "pr474_none", "pr474_shots", "desc", "desc_shots", "desc_inline", "kw",
        "kw_shots", "desc_user", "desc_clock", "pr474_shots+guard+args10", "pr474+guard+rules+args10",
        "pr474_shots+guard+rules+args10", "kw_shots+guard+rules+args10", "rules_new"]
HELD = ["test", "hand", "para"]


def agreement(tag_a, tag_b):
    def load(t):
        return {json.loads(l)["key"]: json.loads(l).get("content") for l in open(OUT / f"results-{t}.jsonl", encoding="utf-8")}
    a, b = load(tag_a), load(tag_b)
    by = Counter()
    for k in set(a) & set(b):
        v = k.split("|")[0]
        by[(v, "n")] += 1
        try:
            pa, pb = json.loads(a[k]), json.loads(b[k])
        except (TypeError, ValueError):
            continue
        by[(v, "same")] += pa == pb
        by[(v, "tool")] += pa.get("tool") == pb.get("tool")
    for v in sorted({v for v, _ in by}):
        print(f"  {tag_a} vs {tag_b} {v:12s}: identical {by[(v, 'same')]}/{by[(v, 'n')]}, same tool {by[(v, 'tool')]}/{by[(v, 'n')]}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="final")
    ap.add_argument("--best", default="rules_new")
    ap.add_argument("--repeats", default="")
    ap.add_argument("-k", type=int, default=20)
    a = ap.parse_args(argv)
    for title, splits in (("ALL", None), ("HELD OUT (test, hand, para)", HELD)):
        table, rows, qs = evaluate(a.tag, splits)
        print(f"\n{title}")
        print_table([t for t in table if t["combo"] in MAIN])
    cats = Counter()
    for p in rows[a.best]:
        cats[(qs[p["id"]]["cat"].split("/")[0], p["all_ok"])] += 1
    print("\nheld-out by kind, " + a.best + ":", {c: f"{cats[(c, True)]}/{cats[(c, True)] + cats[(c, False)]}"
                                                  for c in sorted({c for c, _ in cats})})
    print(f"\nworst {a.k} held-out misses of {a.best}:")
    for m in misses(rows, qs, a.best, a.k):
        print("  ", m)
    for r in [t for t in a.repeats.split(",") if t]:
        agreement(a.tag, r)


if __name__ == "__main__":
    main()
