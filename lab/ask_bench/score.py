"""Score model answers against the known right picks, for each variant and each Python layer.

    python -m lab.ask_bench.score --tag base [--misses 20] [--split test,hand,para]

A pick is "right tool" when its tool is the known one (or an allowed alternative; a refusal is
tool none). "All right" also needs minutes, zone and link inside the known ranges, for the tools
that use them. Seconds per answer are x86 Modal seconds for the model call only: NOT the board's.
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict

from . import overlay
from .payloads import load_questions
from .questions import OUT


def parse(content):
    try:
        p = json.loads(content)
        return p if isinstance(p, dict) else None
    except (TypeError, ValueError):
        return None


def decide(q: str, content, layers: set, zones: dict, links: list) -> tuple:
    """(pick dict, picked_by) the way ask() would end up, for one combination of layers."""
    from agent import ask as A
    from .variants import by_new_rules, fix_typos, guard, parse_minutes, parse_zone
    if "rules474" in layers:
        return A.by_rules(q), "rules"
    raw = q
    if layers & {"rules_only", "guard", "rules", "args", "args10"}:
        q = fix_typos(q)   # the Python layers read a typo-fixed copy; the model gets the question as typed
    if "rules_only" in layers:
        t = "none" if guard(q, zones) else (by_new_rules(q) or "none")
        pick, by = {"tool": t, "minutes": 10, "zone": 0, "link": "any"}, "rules"
    elif "guard" in layers and guard(q, zones):
        pick, by = {"tool": "none", "minutes": 10, "zone": 0, "link": "any"}, "guard"
    elif "rules" in layers and by_new_rules(q):
        pick, by = {"tool": by_new_rules(q), "minutes": 10, "zone": 0, "link": "any"}, "rules"
    else:
        pick, by = parse(content), "llm"
        if pick is None:   # #474: a reply that is not JSON falls back to its keywords
            pick, by = A.by_rules(q), "fallback"
    if layers & {"args", "args10", "rules_only"}:
        pick = dict(pick)
        m = parse_minutes(q)
        keep = by == "llm" and "args" in layers   # args: the model's minutes when none is said; args10: 10
        pick["minutes"] = m if m is not None else (pick.get("minutes") if keep else 10)
        pick["zone"] = parse_zone(q, zones)
    return pick, by


def judge(gold: dict, pick: dict, zones: dict, links: list) -> dict:
    from agent import ask as A
    tool, args = A.checked(pick, zones, links)
    tool = tool or "none"
    tool_ok = tool == gold["tool"] or tool in gold["also"]
    args_ok = True
    if tool_ok and tool != "none" and tool == gold["tool"]:
        m = args.get("minutes")
        if gold["minutes"] is not None and not gold["minutes"][0] <= m <= gold["minutes"][1]:
            args_ok = False
        z = pick.get("zone") if pick.get("zone") in zones else 0
        if gold["zone"] is not None and tool == "presence" and z not in gold["zone"]:
            args_ok = False
        l = pick.get("link") if pick.get("link") in links else "any"
        if gold["link"] is not None and tool == "link_history" and l not in gold["link"]:
            args_ok = False
    return {"tool": tool, "tool_ok": tool_ok, "all_ok": tool_ok and args_ok, "args": args}


from .variants import VARIANTS as MODEL_VARIANTS
LAYER_SETS = [(), ("args",), ("args10",), ("guard",), ("guard", "args10"), ("guard", "rules"), ("guard", "rules", "args"),
              ("guard", "rules", "args10")]


def combos(variants):
    out = [("rules474", None, {"rules474"}), ("rules_new", None, {"rules_only"})]
    for v in variants:
        for ls in LAYER_SETS:
            out.append(("+".join((v,) + ls), v, set(ls)))
    return out


def evaluate(tag: str, splits=None, extra_tags=(), qfile=None):
    overlay.use()
    from agent import ask as A
    zones, links = A.layout()
    qs = {q["id"]: q for q in load_questions(qfile)}
    res = {}
    for t in (tag,) + tuple(extra_tags):
        for l in open(OUT / f"results-{t}.jsonl", encoding="utf-8"):
            r = json.loads(l)
            res[r["key"]] = r
    variants = sorted({k.split("|")[0] for k in res}, key=lambda v: (MODEL_VARIANTS + [v]).index(v))
    ids = sorted({k.split("|")[1] for k in res} & set(qs))
    if splits:
        ids = [i for i in ids if qs[i]["split"] in splits]
    table, rows = [], {}
    for name, v, layers in combos(variants):
        per = []
        for i in ids:
            g = qs[i]
            r = res.get(f"{v}|{i}") if v else {}
            if v and r is None:
                continue
            pick, by = decide(g["q"], r.get("content"), layers, zones, links)
            j = judge(g, pick, zones, links)
            per.append({**j, "id": i, "by": by, "s": r.get("s"), "err": r.get("error"),
                        "prompt_tokens": r.get("prompt_tokens"), "pick": pick})
        rows[name] = per
        table.append(summary(name, per, qs))
    return table, rows, qs


def summary(name, per, qs):
    n = len(per)
    refuse = [p for p in per if qs[p["id"]]["tool"] == "none"]
    answer = [p for p in per if qs[p["id"]]["tool"] != "none"]
    llm_s = [p["s"] for p in per if p["by"] == "llm" and p["s"] is not None]
    by_split = defaultdict(list)
    for p in per:
        by_split[qs[p["id"]]["split"]].append(p["tool_ok"])
    return {"combo": name, "n": n, "tool": sum(p["tool_ok"] for p in per) / n, "all": sum(p["all_ok"] for p in per) / n,
            "refused": sum(p["tool"] == "none" for p in refuse) / max(1, len(refuse)),
            "false_refusal": sum(p["tool"] == "none" for p in answer) / max(1, len(answer)),
            "fallback": sum(p["by"] == "fallback" for p in per) / n,
            "llm_share": len(llm_s) / n, "s_median": statistics.median(llm_s) if llm_s else None,
            "max_prompt_tokens": max((p["prompt_tokens"] or 0 for p in per), default=0),
            "split": {s: round(sum(v) / len(v), 3) for s, v in sorted(by_split.items())}}


def print_table(table):
    print(f"{'combo':38s} {'n':>5s} {'tool':>6s} {'all':>6s} {'refuse':>6s} {'falseR':>6s} {'fallbk':>6s} {'s_x86':>6s}  by split (tool)")
    for t in table:
        s = f"{t['s_median']:.2f}" if t["s_median"] else "  -"
        print(f"{t['combo']:38s} {t['n']:5d} {t['tool']:6.1%} {t['all']:6.1%} {t['refused']:6.1%} {t['false_refusal']:6.1%} "
              f"{t['fallback']:6.1%} {s:>6s}  {t['split']}")


def misses(rows, qs, name, k=20, field="all_ok"):
    bad = [p for p in rows[name] if not p[field]]
    # worst first: a wrong refusal decision, then a wrong tool, then wrong arguments
    def rank(p):
        g = qs[p["id"]]
        return (0 if (g["tool"] == "none") != (p["tool"] == "none") else 1 if not p["tool_ok"] else 2, g["cat"], p["id"])
    return [(qs[p["id"]]["q"], qs[p["id"]]["tool"], p["tool"], p["pick"], qs[p["id"]]["split"]) for p in sorted(bad, key=rank)[:k]]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--extra", default="")
    ap.add_argument("--split", default=None)
    ap.add_argument("--misses", default=None, help="combo name to list misses for")
    ap.add_argument("-k", type=int, default=20)
    ap.add_argument("--field", default="all_ok")
    ap.add_argument("--questions", default=None, help="another question file (default out/questions.jsonl + paraphrases)")
    a = ap.parse_args()
    table, rows, qs = evaluate(a.tag, a.split.split(",") if a.split else None, [t for t in a.extra.split(",") if t],
                               a.questions)
    print_table(table)
    if a.misses:
        for m in misses(rows, qs, a.misses, a.k, a.field):
            print(" ", m)
