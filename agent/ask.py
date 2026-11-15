"""Ask the room a question; the board answers from its own records.

    python -m agent.ask "was anyone here in the last 10 minutes?"
    python -m agent.ask --no-llm "any alerts?"        # pick the tool by keywords only

The language model (llama-server on 127.0.0.1:8091) only picks ONE tool and its arguments;
a JSON schema forces the shape of its reply. Python runs the tool on the store and fills
the answer from the rows, so the model never writes a number or a fact. If the model is
down or slow, the tool is picked by keywords, and the reply says so (picked_by "rules").
A question that fits no tool gets the list of what can be asked.
"""
import argparse
import json
import re
import time
import urllib.request
from pathlib import Path

from store import DB, Store
from .tools import TOOLS

LLM_URL = "http://127.0.0.1:8091"
TIMEOUT_S = 8.0
MAX_QUESTION = 200
MINUTES = (1, 1440, 10)   # least, most, when not said
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
RULES = (("intrusions", r"intru|armed|after hours|break"), ("alerts", r"alert|check.?in|alarm"),
         ("still_spans", r"still|not mov|without mov|no movement|motionless"),
         ("explain_advice", r"advice|advis|router|dead zone"), ("model_card", r"model|train|learn|cloud|private|camera"),
         ("link_history", r"link|signal|dbm|blind|radio"), ("presence", r"anyone|anybody|someone|somebody|who|here|empty|person|people"))


def layout(path=NODES_JSON):
    """({zone id: name}, [link ids]) from radio/nodes.json."""
    with open(path, encoding="utf-8") as f:
        nodes = json.load(f)
    return {int(z["id"]): str(z["name"]) for z in nodes["zones"]}, [l["id"] for l in nodes["links"]]


def schema(zones: dict, links: list) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["tool", "minutes", "zone", "link"],
            "properties": {"tool": {"enum": list(TOOLS) + ["none"]},
                           "minutes": {"type": "integer", "minimum": MINUTES[0], "maximum": MINUTES[1]},
                           "zone": {"enum": [0] + sorted(zones)}, "link": {"enum": ["any"] + list(links)}}}


def can_answer() -> str:
    return "I can answer: " + "; ".join(f.__doc__ for f in TOOLS.values()) + "."


def messages(question: str, zones: dict, links: list) -> list:
    tools = "\n".join(f"- {name}: {f.__doc__}" for name, f in TOOLS.items())
    system = ("Pick the one tool that answers a question about a room sensor. Reply with JSON only.\n"
              f"Tools:\n{tools}\n- none: the question is about something else\n"
              f"minutes: how far back to look ({MINUTES[2]} if not said; an hour is 60).\n"
              f"zone: 0 for anywhere, or {', '.join(f'{z} for {n}' for z, n in sorted(zones.items()))}.\n"
              f"link: any, or one of {', '.join(links)}.")
    return [{"role": "system", "content": system}, {"role": "user", "content": question}]


class Picker:
    """llama-server's chat endpoint with the reply held to a JSON schema. Returns the parsed reply."""

    def __init__(self, url: str = LLM_URL, timeout_s: float = TIMEOUT_S):
        self.url, self.timeout_s = url.rstrip("/") + "/v1/chat/completions", timeout_s

    def __call__(self, msgs: list, json_schema: dict) -> dict:
        body = {"messages": msgs, "max_tokens": 48, "temperature": 0,
                "response_format": {"type": "json_object", "schema": json_schema}}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            return json.loads(json.load(r)["choices"][0]["message"]["content"])


def by_rules(question: str) -> dict:
    """The keyword pick, for when the model can't be reached."""
    q = question.lower()
    tool = next((name for name, pattern in RULES if re.search(pattern, q)), "none")
    n = re.search(r"(\d+)\s*(min|hour|hr)", q)
    minutes = int(n.group(1)) * (1 if n.group(2) == "min" else 60) if n else ("hour" in q and 60) or MINUTES[2]
    return {"tool": tool, "minutes": minutes, "zone": 0, "link": "any"}


def checked(pick, zones: dict, links: list) -> tuple:
    """(tool name or None, arguments) from whatever came back: nothing outside the lists gets through."""
    if not isinstance(pick, dict) or pick.get("tool") not in TOOLS:
        return None, {}
    minutes = pick.get("minutes")
    minutes = MINUTES[2] if not isinstance(minutes, int) or isinstance(minutes, bool) else min(max(minutes, MINUTES[0]), MINUTES[1])
    return pick["tool"], {"minutes": minutes, "zone": pick.get("zone") if pick.get("zone") in zones else None,
                          "link": pick.get("link") if pick.get("link") in links else None}


def ask(question: str, store: Store, llm=None, now_ms=None, zones=None, links=None, timer=time.monotonic) -> dict:
    """{"answer", "rows", "tool", "args", "picked_by": "llm"|"rules", "src", "ms"} for one question.
    src is the newest record's src ("live", "sim" or "replay"; None when the store is empty)."""
    start = timer()
    if zones is None or links is None:
        zones, links = layout()
    question = " ".join(str(question).split())[:MAX_QUESTION]
    pick, picked_by = None, "rules"
    if llm is not None:
        try:
            pick, picked_by = llm(messages(question, zones, links), schema(zones, links)), "llm"
        except Exception:   # down, slow, or not JSON: the keywords still answer
            pick = None
    if pick is None:
        pick = by_rules(question)
    tool, args = checked(pick, zones, links)
    if tool is None:
        out = {"answer": can_answer(), "rows": []}
    else:
        out = TOOLS[tool](store, int(time.time() * 1000) if now_ms is None else now_ms, zones, **args)
    latest = store.latest()
    return {**out, "tool": tool, "args": args, "picked_by": picked_by, "src": latest and latest["src"],
            "ms": round((timer() - start) * 1000)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Ask the room a question; it answers from the store")
    ap.add_argument("question")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--llm", default=LLM_URL, help="llama-server base URL")
    ap.add_argument("--no-llm", action="store_true", help="pick the tool by keywords only")
    args = ap.parse_args(argv)
    reply = ask(args.question, Store(args.db), None if args.no_llm else Picker(args.llm))
    print(reply["answer"])
    for row in reply["rows"]:
        print("  ", json.dumps(row))
    print(f"tool {reply['tool']} {json.dumps(reply['args'])}, picked by {reply['picked_by']}, "
          f"records {reply['src']}, {reply['ms']} ms")


if __name__ == "__main__":
    main()
