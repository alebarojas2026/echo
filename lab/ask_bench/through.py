"""Score a branch's own agent/ask.py end to end, replaying the model answers the bench recorded.

    python -m lab.ask_bench.through --ref ask-clearer-tools --tag final --variant pr474_shots

The branch's agent/ and store/ go to .overlay-<ref>/. Each question goes through that ask()
with an empty store and a model that returns what llama-server answered for the same request,
so the score is the branch's code, not a copy of it. It checks first that the branch sends
exactly the request the bench recorded (same messages, same schema).
"""
import argparse
import json
import time
from pathlib import Path

from . import overlay
from .payloads import load_questions
from .questions import NOW_HM, OUT
from .score import judge, summary, print_table


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--variant", required=True, help="the bench variant whose recorded answers the branch's prompt matches")
    ap.add_argument("--no-llm", action="store_true", help="score the branch with no model at all")
    ap.add_argument("--questions", default=None)
    a = ap.parse_args(argv)
    out = overlay.HERE / f".overlay-{a.ref.replace('/', '_')}"
    overlay.fetch(a.ref, overlay.NODES_REF, out)
    overlay.use(out)
    from agent import ask as A
    from store import Store
    zones, links = A.layout()
    res = {}
    for l in open(OUT / f"results-{a.tag}.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["key"].startswith(a.variant + "|"):
            res[r["key"].split("|")[1]] = r
    pay = {}
    for l in open(OUT / f"payloads-{a.tag}.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if p["key"].startswith(a.variant + "|"):
            pay[p["key"].split("|")[1]] = p["body"]
    qs = {q["id"]: q for q in load_questions(Path(a.questions) if a.questions else None)}
    now_ms = int(time.mktime((2026, 11, 15, NOW_HM[0], NOW_HM[1], 0, 0, 0, -1)) * 1000)
    store = Store(":memory:")
    per, mismatch, asked = [], 0, 0
    for i, g in qs.items():
        if i not in res:
            continue
        sent = {}

        def model(msgs, schema, i=i):
            sent["msgs"], sent["schema"] = msgs, schema
            return json.loads(res[i]["content"])
        reply = A.ask(g["q"], store, None if a.no_llm else model, now_ms=now_ms, zones=zones, links=links)
        if sent:
            asked += 1
            mismatch += sent["msgs"] != pay[i]["messages"] or sent["schema"] != pay[i]["response_format"]["schema"]
        args = reply["args"]
        pick = {"tool": reply["tool"] or "none", "minutes": args.get("minutes"), "zone": args.get("zone") or 0,
                "link": args.get("link") or "any"}
        j = judge(g, pick, zones, links)
        per.append({**j, "id": i, "by": "llm" if sent else "rules", "s": res[i].get("s") if sent else None,
                    "err": None, "prompt_tokens": None, "pick": pick})
    pins = json.loads((out / "pins.json").read_text())
    name = f"{a.ref}@{pins['agent']['commit'][:7]}" + (" no model" if a.no_llm else f" + {a.variant}")
    print_table([summary(name, per, qs)])
    print(f"model asked for {asked} of {len(per)} questions; requests different from the recorded ones: {mismatch}")
    return per, qs


if __name__ == "__main__":
    main()
