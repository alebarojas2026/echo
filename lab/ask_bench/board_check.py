"""Check on the board that its model picks what the x86 bench recorded. Standard library only.

On the PC:   python -m lab.ask_bench.board_check --make --tag final   # writes board50.json
On the board (repo pulled while it still had internet; llama-server up on 127.0.0.1:8091):
             python3 lab/ask_bench/board_check.py
             python3 lab/ask_bench/board_check.py --ask http://127.0.0.1:8080/ask   # also the 3 screen examples

It sends the same 50 requests (the prompt the agent branch sends, same schema, temperature 0)
straight to llama-server and prints how many picks agree with x86, the ones that differ, and
the seconds per answer on the board. Small number differences between x86 and ARM can flip a
close pick, which is what this checks.
"""
import argparse
import json
import statistics
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / "board50.json"
EXAMPLES = ("Was anyone here in the last 10 minutes?", "How long was the last person still?", "Why did the Wi-Fi link drop?")


def make(tag: str, variant: str, n: int = 50):
    from .questions import OUT
    from .payloads import load_questions
    qs = {q["id"]: q for q in load_questions()}
    res = {}
    for l in open(OUT / f"results-{tag}.jsonl", encoding="utf-8"):
        r = json.loads(l)
        if r["key"].startswith(variant + "|") and "content" in r:
            res[r["key"].split("|")[1]] = r["content"]
    bodies = {}
    for l in open(OUT / f"payloads-{tag}.jsonl", encoding="utf-8"):
        p = json.loads(l)
        if p["key"].startswith(variant + "|"):
            bodies[p["key"].split("|")[1]] = p["body"]
    # every tool and every split, the questions the keywords miss first (those are the ones the model sees)
    from .variants import by_new_rules, fix_typos, guard
    ids = sorted(i for i in res if i in qs)
    miss = [i for i in ids if not guard(fix_typos(qs[i]["q"])) and not by_new_rules(fix_typos(qs[i]["q"]))]
    rest = [i for i in ids if i not in miss]
    pick = miss[: n // 2]
    step = max(1, len(rest) // (n - len(pick)))
    pick += rest[::step][: n - len(pick)]
    items = [{"id": i, "q": qs[i]["q"], "body": bodies[i], "x86": json.loads(res[i])} for i in pick]
    FILE.write_text(json.dumps({"variant": variant, "tag": tag, "items": items}, indent=0), encoding="utf-8")
    print(f"{len(items)} requests, {min(len(miss), n // 2)} of them questions the keywords miss -> {FILE}")


def post(url: str, body: dict, timeout: float = 60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def run(llm: str, ask_url=None):
    data = json.loads(FILE.read_text(encoding="utf-8"))
    same, diff, secs = 0, [], []
    for k, it in enumerate(data["items"]):
        t0 = time.monotonic()
        reply = post(llm.rstrip("/") + "/v1/chat/completions", it["body"])
        secs.append(time.monotonic() - t0)
        got = json.loads(reply["choices"][0]["message"]["content"])
        if all(got.get(f) == it["x86"].get(f) for f in ("tool", "minutes", "zone", "link")):
            same += 1
        else:
            diff.append((it["q"], it["x86"], got))
        print(f"{k + 1:2d}/{len(data['items'])} {secs[-1]:5.1f} s  {got.get('tool')}", flush=True)
    print(f"\nsame pick as x86: {same} of {len(data['items'])}")
    for q, a, b in diff:
        print(f"  DIFFERENT  {q!r}\n     x86 {a}\n     board {b}")
    print(f"board seconds per model answer: median {statistics.median(secs):.1f}, slowest {max(secs):.1f}, "
          f"first {secs[0]:.1f} (the first one fills the prompt cache)")
    if ask_url:
        for q in EXAMPLES:
            t0 = time.monotonic()
            r = post(ask_url, {"question": q}, timeout=30)
            print(f"POST /ask {q!r}: tool {r.get('tool')}, picked by {r.get('picked_by')}, {r.get('ms')} ms "
                  f"({time.monotonic() - t0:.1f} s round trip)\n   {r.get('answer')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--tag", default="final")
    ap.add_argument("--variant", default="pr474_shots")
    ap.add_argument("--llm", default="http://127.0.0.1:8091")
    ap.add_argument("--ask", default=None, help="the board's /ask URL, to time the 3 screen examples end to end")
    a = ap.parse_args()
    if a.make:
        make(a.tag, a.variant)
    else:
        run(a.llm, a.ask)
