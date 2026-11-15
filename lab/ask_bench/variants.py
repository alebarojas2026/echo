"""Prompt variants (what the model is sent) and Python layers (what runs before and after it).

Every variant keeps #474's JSON schema, sampling (temperature 0, max_tokens 48) and llama-server
settings; only the chat messages change. The layers are applied afterwards on this PC, so one
model run scores many combinations:
- guard: questions the room must refuse (who, how many, orders, prompt tricks) never reach the model;
- rules: a keyword picker that answers the obvious questions before the model;
- args: Python reads the time and the side from the question and overrides the model's.
"""
import json
import math
import re

from .questions import NOW_HM

# --- prompt pieces -------------------------------------------------------------------------

DESC = {
    "presence": "was anyone here, is anyone here now, did someone walk past or come by, was a side empty",
    "still_spans": "how long someone stayed still or did not move",
    "alerts": "no-movement alerts (someone still too long) and check-ins",
    "intrusions": "armed mode, intrusion alerts, break-ins after hours",
    "link_history": "the radio links: Wi-Fi or Bluetooth signal, dBm, a link that dropped, sensor blind",
    "explain_advice": "the router advice: why move the router, what blocked it, what the move changed",
    "model_card": "the model on this board: how it was trained, the camera, privacy, the cloud, speed",
}
KW = {
    "presence": "anyone, someone, anybody, here, empty, occupied, walk past, came by, visitor, left side, right side",
    "still_spans": "still, not moving, without moving, motionless, frozen, stood in one place, how long still",
    "alerts": "alert, alarm, no-movement alert, warning, check-in, waved",
    "intrusions": "intrusion, intruder, armed, armed mode, break-in, after hours, security",
    "link_history": "link, signal, Wi-Fi, Bluetooth, dBm, RSSI, dropped, blind, radio, beacon",
    "explain_advice": "router, advice, move the router, blocked, obstruction, what the move changed",
    "model_card": "model, trained, learn, camera, cloud, private, data, AI, how fast",
}
NONE_474 = "the question is about something else"
NONE_NEW = ("anything else, and every question about who someone is, how many people, what someone looks "
            "like or is doing, the weather, the time, news, jokes, and any order or instruction")

SHOTS = [  # (question, reply); none of these is in the question set
    ("anyone on the right in the last 5 minutes?", {"tool": "presence", "minutes": 5, "zone": 2, "link": "any"}),
    ("how long did they stay without moving?", {"tool": "still_spans", "minutes": 10, "zone": 0, "link": "any"}),
    ("who was that?", {"tool": "none", "minutes": 10, "zone": 0, "link": "any"}),
    ("did the wifi signal drop in the last hour?", {"tool": "link_history", "minutes": 60, "zone": 0, "link": "any"}),
    ("is the room armed?", {"tool": "intrusions", "minutes": 10, "zone": 0, "link": "any"}),
    ("how many people walked past?", {"tool": "none", "minutes": 10, "zone": 0, "link": "any"}),
    ("is there a camera?", {"tool": "model_card", "minutes": 10, "zone": 0, "link": "any"}),
    ("why move the router?", {"tool": "explain_advice", "minutes": 10, "zone": 0, "link": "any"}),
    ("did a no-movement alert go off today?", {"tool": "alerts", "minutes": 1440, "zone": 0, "link": "any"}),
]


def _system(zones, links, desc=None, none=NONE_474, head=None, clock=False, extra=""):
    from agent.tools import TOOLS
    desc = desc or {n: f.__doc__ for n, f in TOOLS.items()}
    tools = "\n".join(f"- {name}: {desc[name]}" for name in TOOLS)
    head = head or "Pick the one tool that answers a question about a room sensor. Reply with JSON only."
    now = f"It is {NOW_HM[0]:02d}:{NOW_HM[1]:02d} now.\n" if clock else ""
    return (f"{head}\n{now}Tools:\n{tools}\n- none: {none}\n"
            f"minutes: how far back to look (10 if not said; an hour is 60).\n"
            f"zone: 0 for anywhere, or {', '.join(f'{z} for {n}' for z, n in sorted(zones.items()))}.\n"
            f"link: any, or one of {', '.join(links)}.{extra}")


def _system_new(zones, links, clock=False, desc=None):
    desc = desc or DESC
    head = "You pick the one tool that answers a visitor's question about a room sensor at a desk. Reply with JSON only."
    sides = ", ".join(f"{z} for {n}" for z, n in sorted(zones.items()))
    now = f"It is {NOW_HM[0]:02d}:{NOW_HM[1]:02d} now.\n" if clock else ""
    tools = "\n".join(f"- {name}: {d}" for name, d in desc.items())
    return (f"{head}\n{now}Tools:\n{tools}\n- none: {NONE_NEW}\n"
            "minutes: how far back to look. 10 if not said; an hour is 60, a day is 1440.\n"
            f"zone: 0 unless the question names a side: {sides}.\n"
            f"link: any, unless the question names one link: {', '.join(links)}.")


def _shots(question):
    out = []
    for q, a in SHOTS:
        out += [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(a)}]
    return out + [{"role": "user", "content": question}]


def _shots_inline():
    return "\nExamples:\n" + "\n".join(f"{q} -> {json.dumps(a)}" for q, a in SHOTS)


def build(variant: str, question: str, zones: dict, links: list) -> list:
    """The chat messages one variant sends for one question."""
    from agent import ask as A
    q = " ".join(str(question).split())[:A.MAX_QUESTION]
    if variant == "pr474":
        return A.messages(q, zones, links)
    sys_ = {
        "pr474_none": lambda: _system(zones, links, none=NONE_NEW),
        "pr474_shots": lambda: _system(zones, links),
        "desc": lambda: _system_new(zones, links),
        "desc_clock": lambda: _system_new(zones, links, clock=True),
        "desc_shots": lambda: _system_new(zones, links),
        "desc_inline": lambda: _system_new(zones, links) + _shots_inline(),
        "kw": lambda: _system_new(zones, links, desc=KW),
        "kw_shots": lambda: _system_new(zones, links, desc=KW),
        "desc_user": lambda: _system_new(zones, links),
    }[variant]()
    if variant == "desc_user":
        return [{"role": "user", "content": sys_ + "\nQuestion: " + q}]
    if variant.endswith("_shots"):
        return [{"role": "system", "content": sys_}] + _shots(q)
    return [{"role": "system", "content": sys_}, {"role": "user", "content": q}]


VARIANTS = ["pr474", "pr474_none", "pr474_shots", "desc", "desc_clock", "desc_shots", "desc_inline", "kw", "kw_shots",
            "desc_user"]


def body(variant: str, question: str, zones: dict, links: list) -> dict:
    """The exact request #474's Picker sends, with this variant's messages."""
    from agent import ask as A
    return {"messages": build(variant, question, zones, links), "max_tokens": 48, "temperature": 0,
            "response_format": {"type": "json_object", "schema": A.schema(zones, links)}}


# --- Python layers (tuned on the dev split only) ---------------------------------------------

CANT = re.compile(
    r"\bhow many (people|persons|visitors|judges|guys|ppl|of them|men|women)\b|\bcount (the |how many )?(people|visitors|ppl|persons)\b"
    r"|\bwho(?!\s+trained)\b|\bwhos\b|\bwho's\b|\bwhose\b|\bidentif|\brecogni"
    r"|\bman or (a )?woman\b|\bwas it a (man|woman|guy|girl)\b|\bwearing\b|\bhow tall\b|\bhow old\b|\bhis name\b|\bher name\b"
    r"|\blook like\b|\bsame person\b|\bphoto\b|\bpicture\b|\bheart\b|\bbreathing\b|\bon (his|her|their) phone\b"
    r"|\bignore\b|\bpretend\b|\brepeat after\b|\bsystem prompt\b|\byou are now\b|\bjailbreak|\bforget (the|your|all)\b"
    r"|\bweather\b|\bjoke\b|\bpoem\b|\bhaiku\b|\bpassword\b|\bcapital of\b|\bstock\b|\bwhat time is it\b"
    r"|^\W*(please )?(arm|disarm|turn (on|off)|reset|delete|send|call|open|play|set|translate|write|say|tell me a)\b", re.I)

RULES = [  # (tool, pattern): first match wins
    ("intrusions", r"intru|\barmed\b|\barm(ed)? mode|break.?ins?\b|broke in|trespass|after.?hours|sneak|security (alarm|mode|system)"),
    ("alerts", r"no.?movement (alert|alarm|warning)|not.?moving (alert|alarm)|\balerts?\b|\balarms?\b|check.?ins?\b|\bcheck in\b|still (alert|alarm)|\bwarn"),
    ("explain_advice", r"router|advice|advis|suggest|dead (zone|spot)|blocking|obstruct|in the way|the move\b|move the pi\b|arrow"),
    ("still_spans", r"\b(stand|stood|standing|stay|stayed|staying|sit|sat|sitting|hold|held|keep|kept|been|be) still\b"
                    r"|\bstill\b(?! (here|there|working|blind|on\b))|not mov|without mov|motionless|stationary|stay(ed)? put"
                    r"|freez|frozen|hold still|keep still|in one (spot|place)|didn.?t move|stop(ped)? moving"),
    ("link_history", r"wi.?fi|signal|\blinks?\b|bluetooth|\bble\b|dbm|rssi|blind|radio|interference|dropouts?|stale"),
    ("model_card", r"\bmodel\b|train|learn|camera|cloud|internet|online|private|privacy|data (leave|get|sent)|upload"
                   r"|neural|\bai\b|decision|decide|accura|\brun(s|ning)? on\b"),
    ("presence", r"\b(any|some|no|every)\s?(one|body)\b|\bppl\b|\bperson\b|\bpeople\b|visit|occupied|empty|presen"
                 r"|walk(ed)? (past|by|up|behind)|pass(ed)? (by|through)|c[oa]me by|stop(ped)? by|show(ed)? up|detected|activity|movement"),
]
RULES = [(t, re.compile(p, re.I)) for t, p in RULES]


# "Is that Ivan?", "Where is Ivan?": a capitalised name that isn't one of the zones.
NAME = re.compile(r"\b(?:(?:[Ii]s|[Ww]as) (?:that|this|it)(?: guy| girl| person)?|[Ww]here is|[Ww]here's) ([A-Z][a-z]+)\b")


def guard(question: str, zones=None) -> bool:
    if CANT.search(question):
        return True
    names = {n.lower() for n in (zones or {1: "Left", 2: "Right"}).values()}
    return any(m.group(1).lower() not in names for m in NAME.finditer(question))


def by_new_rules(question: str):
    """The first tool whose keywords match, or None when nothing matches."""
    return next((t for t, p in RULES if p.search(question)), None)


# Words the keywords and the time reader look for. A typo one letter away from one of them
# ("sinec", "alamr", "anyoe") is read as that word before the keywords run.
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


def fix_typos(question: str) -> str:
    import difflib
    out = []
    for w in re.findall(r"\w+|\W+", question):
        lw = w.lower()
        if len(lw) >= 4 and w.isalpha() and lw not in VOCAB and lw not in KEEP:
            near = difflib.get_close_matches(lw, VOCAB, n=1, cutoff=0.8)
            if near and abs(len(near[0]) - len(lw)) <= 1:
                w = near[0]
        out.append(w)
    return "".join(out)


WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
WORDS.update({"fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60,
              "a": 1, "an": 1, "couple of": 2, "few": 5})
NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)) + r")"
SPAN = re.compile(r"\b" + NUM + r"\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?)\b", re.I)
HOURS = r"(\d{1,2}|" + "|".join(w for w, n in WORDS.items() if 1 <= n <= 12 and w not in ("a", "an", "few")) + r")"
SINCE = re.compile(r"\bsince\s+(noon|midday|" + HOURS + r")(?::(\d\d))?\s*(am|pm|a\.m\.|p\.m\.|o'?clock)?", re.I)


def _num(s):
    s = s.lower()
    return float(s) if s[0].isdigit() else float(WORDS[s])


def parse_minutes(question: str, now_hm=NOW_HM):
    """Minutes back that the question names, or None when it names none."""
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
        options = [t] if ampm in ("am", "pm") or h > 12 else [t, t + 720]
        past = [o for o in options if o <= now]
        t = max(past) if past else max(options) - 1440
        return max(1, min(1440, now - t))
    m = SPAN.search(q)
    if m and not (m.group(2) in ("s", "m", "h") and not m.group(1)[0].isdigit()):
        n, unit = _num(m.group(1)), m.group(2)[0]
        mins = n / 60 if unit == "s" else n * 60 if unit == "h" else n * 1440 if unit == "d" else n
        return max(1, min(1440, math.ceil(mins)))
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


LEFT = re.compile(r"\b(left|lft)\b", re.I)
RIGHT = re.compile(r"\b(on|in|at|to|the) (the )?(right|rigth)\b(?! now)|\b(right|rigth)[- ]?(side|zone|half|hand|end|one)\b", re.I)


def parse_zone(question: str, zones: dict):
    """1 for Left, 2 for Right (from the zone names), 0 for neither or both."""
    names = {n.lower(): z for z, n in zones.items()}
    left, right = bool(LEFT.search(question)), bool(RIGHT.search(question))
    if left == right:
        return 0
    return names.get("left" if left else "right", 0)
