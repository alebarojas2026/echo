"""Build the exact llama-server requests for each (variant, question), on the PC.

    python -m lab.ask_bench.payloads --tag base [--variants pr474,desc] [--limit 50]

Writes out/payloads-<tag>.jsonl: {"key": "<variant>|<question id>", "body": {...}}, grouped by
variant so the fixed start of each prompt stays cached in the one slot, as on the board.
The agent code comes from the overlay (python -m lab.ask_bench.overlay).
"""
import argparse
import json

from . import overlay
from .questions import OUT


def load_questions(path=None) -> list:
    path = path or OUT / "questions.jsonl"
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    para = OUT / "paraphrases.jsonl"
    if path == OUT / "questions.jsonl" and para.exists():
        rows += [json.loads(l) for l in open(para, encoding="utf-8")]
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--variants", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--splits", default=None, help="e.g. dev,test")
    a = ap.parse_args(argv)
    overlay.use()
    from agent import ask as A
    from .variants import VARIANTS, body
    zones, links = A.layout()
    variants = a.variants.split(",") if a.variants else VARIANTS
    qs = load_questions()
    if a.splits:
        qs = [q for q in qs if q["split"] in a.splits.split(",")]
    if a.limit:
        qs = qs[:: max(1, len(qs) // a.limit)][: a.limit]
    n = 0
    with open(OUT / f"payloads-{a.tag}.jsonl", "w", encoding="utf-8") as f:
        for v in variants:
            for q in qs:
                f.write(json.dumps({"key": f"{v}|{q['id']}", "body": body(v, q["q"], zones, links)}) + "\n")
                n += 1
    print(f"{n} requests ({len(variants)} variants x {len(qs)} questions), zones {zones}, {len(links)} links")


if __name__ == "__main__":
    main()
