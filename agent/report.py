"""The incident report after an armed stretch, from the board's own records.

    python -m agent.report            # the last armed stretch
    python -m agent.report --no-llm   # the fixed template only

Every field is a query on the store (CONTRACTS.md section 10, GET /report). `text` says them in
plain words. The on-board model may write it from the fields, but its text is only used when
every number in it is one of the report's own numbers, it uses none of the words the screen must
never say, and it arrives within 8 s. Otherwise the fixed template is used. Nothing here knows
or says who anyone was.
"""
import argparse
import json
import re
import time
import urllib.request

from narrator.narrate import BANNED, within
from store import DB, Store
from .ask import LLM_URL, NODES_JSON, layout
from .tools import clock

TIMEOUT_S = 8.0
MAX_WORDS = 60
NUMBER = re.compile(r"\d+(?:\.\d+)?")
WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen twenty").split()
NOT_OUR_WORDS = re.compile(r"\b(burglar\w*|thie(f|ves)|robber\w*|criminal\w*|suspect\w*|break.?in)\b", re.IGNORECASE)


def stretch(store: Store, now_ms: int = 0):
    """(from_t, to_t or None) of the last armed stretch, or None when the space was never armed."""
    armed = store.events(0, ("armed",))
    if not armed:
        return None
    start = armed[-1]["t"]
    ended = store.events(start, ("disarmed",))
    return start, (ended[0]["t"] if ended else None)


def facts(store: Store, from_t: int, to_t, now_ms: int) -> dict:
    """The report's fields, each one counted from the store."""
    end = now_ms if to_t is None else to_t
    seconds = [r for r in store.seconds(from_t) if r["t"] <= end]
    events = [e for e in store.events(from_t, ("intrusion", "tamper")) if e["t"] <= end]
    intrusions = [{"t": e["t"], **({"zone": e["info"]["zone"]} if "zone" in e["info"] else {"link": e["info"].get("link")})}
                  for e in events if e["kind"] == "intrusion"]
    return {"armed_from_t": from_t, "armed_to_t": to_t, "intrusions": intrusions,
            "present_s": sum(r["present"] == 1 and r["kind"] == "person" for r in seconds),
            "passed_by": None,   # the brain has no passed-by rule
            "tamper": [{"t": e["t"], "node": e["info"].get("node")} for e in events if e["kind"] == "tamper"],
            "blind_s": sum(r["health"] == "blind" for r in seconds), "rows": len(seconds)}


def _where(hit: dict, zones: dict) -> str:
    if "zone" in hit:
        name = zones.get(hit["zone"])
        if not name:
            return "in the space"
        return f"on the {name.lower()}" if name.lower() in ("left", "right") else f"in the {name} zone"
    return f"on the path {hit['link']}"


def device_names(path=NODES_JSON) -> dict:
    """{node id: its name in radio/nodes.json}, for the nodes that have one."""
    try:
        with open(path, encoding="utf-8") as f:
            return {n["id"]: n["name"] for n in json.load(f)["nodes"] if n.get("name")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def template(f: dict, zones: dict, names=None) -> str:
    """The fixed report: one sentence per field."""
    armed = (f"Armed at {clock(f['armed_from_t'])} and still armed." if f["armed_to_t"] is None
             else f"Armed from {clock(f['armed_from_t'])} to {clock(f['armed_to_t'])}.")
    hits = f["intrusions"]
    intrusion = ("No intrusion alert." if not hits else
                 f"Intrusion alerts: {len(hits)}, the first {_where(hits[0], zones)} at {clock(hits[0]['t'])}.")
    tamper = ""
    if f["tamper"]:
        node = f["tamper"][0]["node"]
        device = (device_names() if names is None else names).get(node)
        said = (device if device.startswith("Pi ") else f"the {device}") if device else f"the device {node}"
        tamper = (f" Tamper alerts: {len(f['tamper'])}; {said} went quiet first, at {clock(f['tamper'][0]['t'])}.")
    blind = f" The sensor was blind for {f['blind_s']} s." if f["blind_s"] else ""
    return f"{armed} {intrusion} Someone was here for {f['present_s']} s.{tamper}{blind}"


def allowed(f: dict) -> tuple:
    """(numbers a report may contain, clock times it may contain), all from its own fields."""
    numbers = {f["present_s"], f["blind_s"], len(f["intrusions"]), len(f["tamper"])}
    numbers |= {h["zone"] for h in f["intrusions"] if "zone" in h}
    times = [f["armed_from_t"], f["armed_to_t"]] + [x["t"] for x in f["intrusions"] + f["tamper"]]
    return {float(n) for n in numbers}, {clock(t) for t in times if t is not None}


def problem(text: str, f: dict):
    """Why this text can't be the report, or None if it can."""
    text = " ".join(str(text).split())
    if not text:
        return "empty"
    if len(text.split()) > MAX_WORDS:
        return f"more than {MAX_WORDS} words"
    bad = BANNED.search(text) or NOT_OUR_WORDS.search(text)
    if bad:
        return f"a word we never use ({bad.group(0)})"
    numbers, times = allowed(f)
    rest = text
    for t in sorted(times, key=len, reverse=True):
        rest = rest.replace(t, " ")
    for n in NUMBER.findall(rest):
        if float(n) not in numbers:
            return f"a number that is not in the report ({n})"
    for word in re.findall(r"[a-z]+", rest.lower()):
        if word in WORDS and float(WORDS.index(word)) not in numbers:
            return f"a number that is not in the report ({word})"
    return None


def messages(f: dict, zones: dict) -> list:
    return [{"role": "system", "content":
             "You write a short incident report for the screen of a room sensor. Rewrite the facts as one "
             "short paragraph in plain words. Use only the facts given and keep every number and time exactly "
             "as written. Call a person someone. Say intrusion alert. Reply with the paragraph only."},
            {"role": "user", "content": "Facts: " + template(f, zones)}]


class Writer:
    """llama-server's chat endpoint, for one paragraph."""

    def __init__(self, url: str = LLM_URL, timeout_s: float = TIMEOUT_S):
        self.url, self.timeout_s = url.rstrip("/") + "/v1/chat/completions", timeout_s

    def __call__(self, msgs: list) -> str:
        body = {"messages": msgs, "max_tokens": 120, "temperature": 0.2}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            return json.load(r)["choices"][0]["message"]["content"] or ""


def write(f: dict, zones: dict, llm=None, timeout_s: float = TIMEOUT_S) -> tuple:
    """(text, where it came from): the model's paragraph when it passes `problem`, else the template."""
    text = template(f, zones)
    if llm is None:
        return text, "template"
    try:
        written = " ".join(within(timeout_s, llm, messages(f, zones)).split())
    except Exception as e:   # slow, down, or a reply we can't read
        return text, f"template ({e or type(e).__name__})"
    why = problem(written, f)
    return (written, "llm") if why is None else (text, f"template ({why})")


def report(store: Store, llm=None, from_t=None, to_t=None, now_ms=None, zones=None, timeout_s=TIMEOUT_S,
           timer=time.monotonic, said=None):
    """The report (section 10), or None when no stretch was asked for and the space was never armed.
    said, if given, is called with where the text came from ("llm", "template", "template (why)")."""
    start = timer()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if from_t is None:
        last = stretch(store, now_ms)
        if last is None:
            return None
        from_t, to_t = last
    zones = layout()[0] if zones is None else zones
    f = facts(store, from_t, to_t, now_ms)
    text, why = write(f, zones, llm, timeout_s)
    if said:
        said(why)
    return {**f, "text": text, "ms": round((timer() - start) * 1000)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print the incident report for the last armed stretch")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--llm", default=LLM_URL, help="llama-server base URL")
    ap.add_argument("--no-llm", action="store_true", help="the fixed template only")
    args = ap.parse_args(argv)
    why = []
    out = report(Store(args.db), None if args.no_llm else Writer(args.llm), said=why.append)
    if out is None:
        print("The space has not been armed, so there is no report.")
        return 1
    print(out["text"])
    print(json.dumps({k: v for k, v in out.items() if k != "text"}))
    print(f"text from: {why[0]}, {out['ms']} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
