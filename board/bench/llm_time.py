"""Times narrator sentences through llama-server: prompt speed, generation speed, wall time.

    python board/bench/llm_time.py                             # warm up, then one sentence
    python board/bench/llm_time.py --every 8 --seconds 300     # one every 8 s for 5 minutes

Same prompt and settings as narrator/narrate.py, so prompt caching works as it does live.
PASS (exit 0) when every timed sentence took 8 s or less.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from narrator import narrate

LIMIT_MS = 8000


def events(zones=None):
    """The events to time, in zones the layout has (narrate.ZONES, read from radio/nodes.json):
    the alert in the zone with the shortest no-movement limit, the rest spread over the zones.
    A zone the layout doesn't have would leave the zone and the limit out of the prompt."""
    zones = narrate.ZONES if zones is None else zones
    ids = sorted(zones)
    limited = [z for z in ids if zones[z][1]]

    def zone(i):
        return {"zone": ids[i % len(ids)]} if ids else {}
    alert = {"zone": min(limited, key=lambda z: zones[z][1])} if limited else zone(0)
    return [("alert_on", alert), ("enter", zone(1)), ("zone_change", zone(2)),
            ("object_on", {"node": "pi5"}), ("exit", zone(0))]


EVENTS = events()


def ask(url, kind, info, timeout_s=60.0):
    """One sentence for one event, with llama-server's own timings when it sends them."""
    facts = narrate.template(kind, info)
    body = {"messages": narrate.prompt(kind, facts), "max_tokens": 40, "temperature": 0.2,
            "stop": ["\n"], "cache_prompt": True}   # the same request as narrate.LlamaServer
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        reply = json.load(r)
    tm = reply.get("timings") or {}
    text = (reply["choices"][0]["message"].get("content") or "").strip()
    return {"kind": kind, "wall_ms": round((time.perf_counter() - t0) * 1000), "text": text,
            "prompt_n": tm.get("prompt_n"), "prompt_tok_s": tm.get("prompt_per_second"),
            "gen_n": tm.get("predicted_n"), "gen_tok_s": tm.get("predicted_per_second"),
            "problem": narrate.problem(narrate.clean(text), facts, camera_off=True)}


def line(r):
    tok_s = {k: "?" if r[k] is None else f"{r[k]:.1f}" for k in ("prompt_tok_s", "gen_tok_s")}
    used = f"template instead ({r['problem']})" if r["problem"] else "used"
    return (f"{r['kind']}: prompt {r['prompt_n']} new tokens at {tok_s['prompt_tok_s']} tok/s, "
            f"generation {r['gen_n']} tokens at {tok_s['gen_tok_s']} tok/s, wall {r['wall_ms']} ms "
            f"(limit {LIMIT_MS}) | {r['text']!r}, {used}")


def run(url, every=0.0, seconds=0.0, out=print):
    """Warm up (not counted), then one sentence, or one every `every` s for `seconds`."""
    ask(url, *EVENTS[1], timeout_s=120)
    results, start = [], time.monotonic()
    while True:
        kind, info = EVENTS[len(results) % len(EVENTS)]
        try:
            r = ask(url, kind, info)
        except OSError as e:   # a timeout or a refused connection counts against the model
            r = dict.fromkeys(("prompt_n", "prompt_tok_s", "gen_n", "gen_tok_s", "wall_ms"))
            r.update(kind=kind, text=f"no reply: {e}", problem="no reply")
        results.append(r)
        out(line(r))
        if not every or time.monotonic() - start + every > seconds:
            return results
        time.sleep(max(0.0, start + len(results) * every - time.monotonic()))


def verdict(results):
    walls = [r["wall_ms"] for r in results]
    bad, worst = sum(w is None or w > LIMIT_MS for w in walls), max(filter(None, walls), default=None)
    return not bad, f"{len(walls)} sentences, {bad} over {LIMIT_MS} ms or failed, worst {worst} ms"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--llm", default=narrate.LLM_URL)
    ap.add_argument("--every", type=float, default=0.0, help="seconds between sentences")
    ap.add_argument("--seconds", type=float, default=0.0, help="keep going this long")
    a = ap.parse_args(argv)
    ok, summary = verdict(run(a.llm, a.every, a.seconds, out=lambda s: print(s, flush=True)))
    print(f"{'PASS' if ok else 'FAIL'}: {summary}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
