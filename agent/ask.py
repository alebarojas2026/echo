"""Ask the room a question; the board answers from its own records.

    python -m agent.ask "was anyone here in the last 10 minutes?"
    python -m agent.ask --no-llm "any alerts?"        # pick the tool by keywords only

The language model (llama-server on 127.0.0.1:8091) only picks ONE tool and its arguments;
a JSON schema forces the shape of its reply. Python runs the tool on the store and fills
the answer from the rows, so the model never writes a number or a fact. A question that
fits no tool gets the list of what can be asked.

Before the model:
- a question the records can't answer (who someone is, how many people, orders, tricks
  aimed at the prompt) gets the list at once;
- a question with a plain keyword ("armed", "router", "still", "Wi-Fi", ...) is picked by
  keywords. The model only sees the rest, and if it is down or slow they get the list.
picked_by says which one picked: "llm" or "rules".
"What happened?" (and "tell me the story", "who was here", "replay it") goes to the detective
(agent/detective.py): a story in time order from the stored records, with its steps, the records
it cites and whether the sealed chain verified. It never waits on the model.
The time ("since 2", "in the last hour") and the zone ("on the left") are read from the
question by Python, never guessed by the model. A question test (lab/ask_bench on the
lab-ask-bench branch) checks all of this against a few thousand questions.
"""
import argparse
import difflib
import json
import math
import re
import time
import urllib.request
from pathlib import Path

from store import DB, Store
from .tools import TOOLS, current_spot
from . import detective, room_facts

LLM_URL = "http://127.0.0.1:8091"
TIMEOUT_S = 8.0
MAX_QUESTION = 200
MINUTES = (1, 1440, 10)   # least, most, when not said
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"

# Questions the records can't answer: who someone is, how many people, what they look like or
# are doing, orders, tricks aimed at the prompt, and things that aren't about the room.
CANT = re.compile(
    r"\bhow many (people|persons|visitors|judges|guys|ppl|of them|men|women)\b|\bcount (the |how many )?(people|visitors|ppl|persons)\b"
    r"|\bwho(?!\s+trained)\b|\bwhos\b|\bwho's\b|\bwhose\b|\bidentif|\brecogni"
    r"|\bman or (a )?woman\b|\bwas it a (man|woman|guy|girl)\b|\bwearing\b|\bhow tall\b|\bhow old\b|\bhis name\b|\bher name\b"
    r"|\blook like\b|\bsame person\b|\bphoto\b|\bpicture\b|\bheart\b|\bbreathing\b|\bon (his|her|their) phone\b"
    r"|\bignore\b|\bpretend\b|\brepeat after\b|\bsystem prompt\b|\byou are now\b|\bjailbreak|\bforget (the|your|all)\b"
    r"|\bweather\b|\bjoke\b|\bpoem\b|\bhaiku\b|\bpassword\b|\bcapital of\b|\bstock\b|\bwhat time is it\b"
    r"|^\W*(please )?(arm|disarm|turn (on|off)|reset|delete|send|call|open|play|set|translate|write|say|tell me a)\b", re.I)
# "Is that Robin?", "Where is Robin?": a capitalised name that isn't one of the zones.
NAME = re.compile(r"\b(?:(?:[Ii]s|[Ww]as) (?:that|this|it)(?: guy| girl| person)?|[Ww]here is|[Ww]here's) ([A-Z][a-z]+)\b")
CANT_ANSWER = "I only answer from this room's records, and they never say who someone is or how many people there were."

# "What happened?": the detective tells the story from the records (agent/detective.py).
STORY = re.compile(r"\bwhat(?:'s| has| had)?\b(?:\s+\w+){0,2}\s+happened\b|\bwhat (just )?went on\b|\btell me the story\b"
                   r"|\bthe story\b|\breplay\b|\bwho (was|were|came|has been|had been) (here|there|in|by|around)\b"
                   r"|\bwhat did (you|it|the (board|room|record)) (see|sense|notice|record|catch)\b|\bwhat was recorded\b", re.I)
# "Who was here?" is a story question: the story says what happened and never who it was.
WHO_HERE = re.compile(r"\bwho (was|were|came|has been|had been) (here|there|in|by|around)\b", re.I)
NOT_WHO = "I can't tell who anyone is, only what happened. "

RULES = [  # (tool, keywords): first match wins, so the order matters
    ("intrusions", r"intru|\barmed\b|\barm(ed)? mode|break.?ins?\b|broke in|trespass|after.?hours|sneak|security (alarm|mode|system)"),
    ("alerts", r"no.?movement (alert|alarm|warning)|not.?moving (alert|alarm)|\balerts?\b|\balarms?\b|check.?ins?\b|\bcheck in\b|still (alert|alarm)|\bwarn"),
    ("explain_advice", r"router|advice|advis|suggest|dead (zone|spot)|\bblock(?:ed|ing)?\b|obstruct|in the way|the move\b|move the pi\b|arrow"),
    ("still_spans", r"\b(stand|stood|standing|stay|stayed|staying|sit|sat|sitting|hold|held|keep|kept|been|be) still\b"
                    r"|\bstill\b(?! (here|there|working|blind|on\b))|not mov|without mov|motionless|stationary|stay(ed)? put"
                    r"|freez|frozen|hold still|keep still|in one (spot|place)|didn.?t move|stop(ped)? moving"),
    ("link_history", r"wi.?fi|signal|\blinks?\b|bluetooth|\bble\b|dbm|rssi|blind|radio|interference|dropouts?|stale"),
    ("model_card", r"\bmodel\b|train|learn|camera|cloud|internet|online|private|privacy|data (leave|get|sent)|upload"
                   r"|neural|\bai\b|decision|decide|accura|\brun(s|ning)? on\b"),
    ("presence", r"what.*happening|\bmoving\b|\b(any|some|no|every)\s?(one|body)\b|\bppl\b|\bperson\b|\bpeople\b|visit|occupied|empty|presen"
                 r"|walk(ed)? (past|by|up|behind)|pass(ed)? (by|through)|c[oa]me by|stop(ped)? by|show(ed)? up|detected|activity|movement"),
]
RULES = [(t, re.compile(p, re.I)) for t, p in RULES]

# Words the keywords and the time reader look for. A typo one letter away from one of them
# ("sinec", "alamr", "anyoe") is read as that word first. KEEP: real words that are close.
VOCAB = sorted(set("""
since minutes minute hours hour today seconds right left side empty anyone anybody someone somebody person people
visitors visited occupied presence detected movement still standing frozen motionless stationary moving without stay
alert alerts alarm alarms warning check intrusion intrusions intruder intruders armed break trespassed security
signal signals link links wifi bluetooth radio blind interference dropouts router advice advise suggest blocking
obstruction camera model trained training learn cloud internet private privacy decision accurate many count
""".split()))
KEEP = set("""
mode modes wearing hearing stand stands sits time times with were what when here there come came went move moved moves wave waved
rain raining light lights sign signs like lift many arms army alter mail sale stall stalls rights sight sites
could would should clear cleared clears night ours lines
""".split())

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
WORDS.update({"fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60,
              "a": 1, "an": 1, "couple of": 2, "few": 5})
NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)) + r")"
SPAN = re.compile(r"\b" + NUM + r"\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?)\b", re.I)
HOURS = r"(\d{1,2}|" + "|".join(w for w, n in WORDS.items() if 1 <= n <= 12 and w not in ("a", "an", "few")) + r")"
SINCE = re.compile(r"\bsince\s+(noon|midday|" + HOURS + r")(?::(\d\d))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?", re.I)
LEFT = re.compile(r"\b(left|lft)\b", re.I)
RIGHT = re.compile(r"\b(on|in|at|to|the) (the )?(right|rigth)\b(?! now)|\b(right|rigth)[- ]?(side|zone|half|hand|end|one)\b", re.I)

SHOTS = [  # example questions and picks, sent before the real question. Python reads the zone, so it is 0 in each.
    ("anyone on the right in the last 5 minutes?", {"tool": "presence", "minutes": 5, "zone": 0, "link": "any"}),
    ("how long did they stay without moving?", {"tool": "still_spans", "minutes": 10, "zone": 0, "link": "any"}),
    ("who was that?", {"tool": "none", "minutes": 10, "zone": 0, "link": "any"}),
    ("did the wifi signal drop in the last hour?", {"tool": "link_history", "minutes": 60, "zone": 0, "link": "any"}),
    ("is the room armed?", {"tool": "intrusions", "minutes": 10, "zone": 0, "link": "any"}),
    ("how many people walked past?", {"tool": "none", "minutes": 10, "zone": 0, "link": "any"}),
    ("is there a camera?", {"tool": "model_card", "minutes": 10, "zone": 0, "link": "any"}),
    ("why move the router?", {"tool": "explain_advice", "minutes": 10, "zone": 0, "link": "any"}),
    ("did a no-movement alert go off today?", {"tool": "alerts", "minutes": 1440, "zone": 0, "link": "any"}),
]


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
    shots = []
    for q, pick in SHOTS:
        shots += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(pick)}]
    return [{"role": "system", "content": system}] + shots + [{"role": "user", "content": question}]


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


def fix_typos(question: str) -> str:
    """The question with words one typo away from a keyword read as that keyword."""
    out = []
    for w in re.findall(r"\w+|\W+", question):
        lw = w.lower()
        if len(lw) >= 4 and w.isalpha() and lw not in VOCAB and lw not in KEEP:
            near = difflib.get_close_matches(lw, VOCAB, n=1, cutoff=0.8)
            if near and abs(len(near[0]) - len(lw)) <= 1:
                w = near[0]
        out.append(w)
    return "".join(out)


def cant_answer(question: str, zones: dict) -> bool:
    """True for a question the records can't answer (who, how many, orders, prompt tricks)."""
    if CANT.search(question):
        return True
    names = {n.lower() for n in zones.values()}
    names.update(("wi", "wifi", "bluetooth"))  # Wi-Fi is a link, not a person's name.
    return any(m.group(1).lower() not in names for m in NAME.finditer(question))


def keyword_tool(question: str):
    """The first tool whose keywords match, or None."""
    specific = room_facts.intent(question)
    if specific:
        return specific[1]
    return next((tool for tool, pattern in RULES if pattern.search(question)), None)


def _num(s: str) -> float:
    s = s.lower()
    return float(s) if s[0].isdigit() else float(WORDS[s])


def minutes_said(question: str, now_hm: tuple):
    """How many minutes back the question asks about, or None when it names no time.
    now_hm = (hour, minute) of the board's clock, for "since 2" and "today"."""
    q = question.lower()
    now = now_hm[0] * 60 + now_hm[1]
    if re.search(r"half (an )?hour", q):
        return 30
    if re.search(r"quarter (of an )?hour", q):
        return 15
    m = SINCE.search(q)
    if m:
        if m.group(1) in ("noon", "midday"):
            h, mm = 12, 0
        else:
            h, mm = int(_num(m.group(1))), int(m.group(3) or 0)
            if h > 24 or mm > 59:
                return None
        ampm = (m.group(4) or "").replace(".", "")
        t = h * 60 + mm
        if ampm == "pm" and h < 12:
            t += 720
        options = [t] if ampm in ("am", "pm") or h > 12 else [t, t + 720]   # "since 2" is the latest 2 o'clock
        past = [o for o in options if o <= now]
        t = max(past) if past else max(options) - 1440
        return max(MINUTES[0], min(MINUTES[1], now - t))
    m = SPAN.search(q)
    if m and not (m.group(2) in ("s", "m", "h") and not m.group(1)[0].isdigit()):
        n, unit = _num(m.group(1)), m.group(2)[0]
        mins = n / 60 if unit == "s" else n * 60 if unit == "h" else n * 1440 if unit == "d" else n
        return max(MINUTES[0], min(MINUTES[1], math.ceil(mins)))
    m = re.search(r"\b(last|past|this) (minute|hour|day)\b", q)
    if m:
        return {"minute": 1, "hour": 60, "day": 1440}[m.group(2)]
    if re.search(r"\byesterday\b", q):
        return 1440
    if re.search(r"\b(today|so far today|this morning)\b", q):
        return max(1, now)
    if re.search(r"\bthis afternoon\b", q):
        return max(1, now - 12 * 60)
    if re.search(r"\b(right now|at the moment|at this moment|currently)\b", q):
        return 1
    if re.search(r"\b(just now|a moment ago|a bit ago|a minute ago)\b", q):
        return 2
    if re.search(r"\b(a few minutes ago|last few minutes)\b", q):
        return 5
    return None


def zone_said(question: str, zones: dict) -> int:
    """The one zone the question names ("on the left", "in Right", "the bathroom"), else 0."""
    hits = set()
    for z, name in zones.items():
        n = name.lower()
        pattern = LEFT if n == "left" else RIGHT if n == "right" else re.compile(rf"\b{re.escape(n)}\b", re.I)
        if pattern.search(question):
            hits.add(z)
    return hits.pop() if len(hits) == 1 else 0


def story_question(question: str) -> bool:
    """True for "what happened?" and the like, which the detective answers."""
    return bool(STORY.search(question))


def devices(path) -> dict:
    """{node id: its name in radio/nodes.json}, for the sentences that name a device ("Pi B")."""
    try:
        with open(path, encoding="utf-8") as f:
            return {n["id"]: n["name"] for n in json.load(f)["nodes"] if n.get("name")}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def tell(question: str, store: Store, now_ms: int, zones: dict, nodes_path=None, writer=None) -> dict:
    """The detective's reply (tool "story"): the story of the stretch the question asks about."""
    from_t, to_t, minutes = detective.window(question, now_ms, minutes_said)
    out = detective.investigate(store, from_t, to_t, zones, devices(nodes_path or NODES_JSON), writer)
    if WHO_HERE.search(question):
        out["answer"] = NOT_WHO + out["answer"]
    out["rows"] = out["rows"] + [{"row": "asked", "minutes": minutes}]
    return {**out, "tool": "story", "args": {"minutes": minutes, "zone": None, "link": None}}


def by_rules(question: str, now_hm=None) -> dict:
    """The keyword pick: the tool from the keywords ("none" when nothing matches)."""
    now_hm = now_hm or time.localtime()[3:5]
    said = minutes_said(question, now_hm)
    return {"tool": keyword_tool(question) or "none", "minutes": MINUTES[2] if said is None else said,
            "zone": 0, "link": "any"}


def checked(pick, zones: dict, links: list) -> tuple:
    """(tool name or None, arguments) from whatever came back: nothing outside the lists gets through."""
    if not isinstance(pick, dict) or pick.get("tool") not in TOOLS:
        return None, {}
    minutes = pick.get("minutes")
    minutes = MINUTES[2] if not isinstance(minutes, int) or isinstance(minutes, bool) else min(max(minutes, MINUTES[0]), MINUTES[1])
    return pick["tool"], {"minutes": minutes, "zone": pick.get("zone") if pick.get("zone") in zones else None,
                          "link": pick.get("link") if pick.get("link") in links else None}


USES_MINUTES = ("presence", "still_spans", "alerts", "intrusions", "link_history")


def ask(question: str, store: Store, llm=None, now_ms=None, zones=None, links=None, timer=time.monotonic,
        nodes_path=None, privacy_reader=None, writer=None) -> dict:
    """{"answer", "rows", "tool", "args", "picked_by": "llm"|"rules", "src", "ms"} for one question.
    src is the newest record's src ("live", "sim" or "replay"; None when the store is empty).
    A "what happened" question gets the detective's story, with "steps", "cites" and "chain_ok" too;
    writer, if given, is the on-board model that may smooth the story's wording."""
    start = timer()
    if zones is None or links is None:
        zones, links = layout(nodes_path or NODES_JSON)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    question = " ".join(str(question).split())[:MAX_QUESTION]
    read = fix_typos(question)   # the keywords and the time read this; the model gets the question as typed
    if story_question(read) and not any(cant_answer(WHO_HERE.sub(" ", q), zones) for q in (question, read)):
        out = tell(read, store, now_ms, zones, nodes_path, writer)
        latest = store.latest()
        return {**out, "picked_by": "rules", "src": latest and latest["src"], "ms": round((timer() - start) * 1000)}
    refused = cant_answer(question, zones) or cant_answer(read, zones)
    pick, picked_by = {"tool": "none"}, "rules"
    if not refused:
        tool = keyword_tool(read)
        if tool:
            pick = {"tool": tool, "link": "any"}
        elif llm is not None:
            try:
                pick, picked_by = llm(messages(question, zones, links), schema(zones, links)), "llm"
            except Exception:   # down, slow, or not JSON: the list of what can be asked
                pick = {"tool": "none"}
    if isinstance(pick, dict):
        said = minutes_said(read, time.localtime(now_ms / 1000)[3:5])
        pick = {**pick, "minutes": MINUTES[2] if said is None else said, "zone": zone_said(read, zones)}
    tool, args = checked(pick, zones, links)
    if tool is None:
        # The list comes first, as section 10 says; a refusal adds why after it.
        out = {"answer": can_answer() + (" " + CANT_ANSWER if refused else ""), "rows": []}
    else:
        specific = room_facts.intent(read)
        current = not specific and len(zones) == 1 and tool in ("presence", "still_spans") and re.search(
            r"right now|currently|at the moment|what.*happening|^(is|are)\b", read, re.I)
        current = current and not re.search(r"\b(last|past|since|today|yesterday)\b", read, re.I)
        if specific:
            out = room_facts.answer(specific[0], store, now_ms, args["minutes"], nodes_path or room_facts.NODES,
                                    privacy_reader, one_spot=len(zones) == 1)
        elif current:
            out = current_spot(store, now_ms, zones, nodes_path)
        else:
            out = TOOLS[tool](store, now_ms, zones, nodes_path=nodes_path, **args)
        if tool in USES_MINUTES or specific:   # the minutes in the answer are in a row too
            out = {**out, "rows": out["rows"] + [{"row": "asked", "minutes": args["minutes"]}]}
    latest = store.latest()
    return {**out, "tool": tool, "args": args, "picked_by": picked_by, "src": latest and latest["src"],
            "ms": round((timer() - start) * 1000)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Ask the room a question; it answers from the store")
    ap.add_argument("question")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--llm", default=LLM_URL, help="llama-server base URL")
    ap.add_argument("--no-llm", action="store_true", help="pick the tool by keywords only")
    ap.add_argument("--smooth", action="store_true", help="let the model smooth a story's wording (it waits on the model)")
    args = ap.parse_args(argv)
    writer = None
    if args.smooth and not args.no_llm:
        from .report import Writer
        writer = Writer(args.llm)
    reply = ask(args.question, Store(args.db), None if args.no_llm else Picker(args.llm), writer=writer)
    print(reply["answer"])
    for row in reply["rows"]:
        print("  ", json.dumps(row))
    for step in reply.get("steps", []):
        print(f"   step {step['tool']}: {step['rows']} rows, {step['ms']} ms")
    if "chain_ok" in reply:
        print(f"   chain_ok {reply['chain_ok']}, cites {reply.get('cites', reply.get('cites_t'))}")
    print(f"tool {reply['tool']} {json.dumps(reply['args'])}, picked by {reply['picked_by']}, "
          f"records {reply['src']}, {reply['ms']} ms")


if __name__ == "__main__":
    main()
