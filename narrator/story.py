"""What happened, as a short story in time order, built from the board's stored records only.

    from narrator import story
    items = story.timeline(events, seconds, zones, devices, from_t, to_t)
    text = story.tell(items)          # "2:14 AM. Somebody stepped in at the desk and stood still for 40 seconds. ..."

Each item is one sentence about one thing that happened, with the clock time it happened and the
records it came from (their `seq` when the store seals records, else their time t). The sentences are
fixed templates filled from the rows: every number and every time in them is read from a record.
The on-board model may only smooth the wording (`smooth`), and its text is used only when it keeps
every number and time exactly and adds none; otherwise the template story is the answer.
It never says who anyone is: a person is always "somebody".
"""
from __future__ import annotations

import re
import time

from narrator.narrate import BANNED, within

STILL_MIN_S = 3          # a still or moving stretch shorter than this is not worth a sentence
PASSED_GAP_MS = 3000     # a passed_by this close after an exit makes that visit a walk-through
SMOOTH_TIMEOUT_S = 8.0   # as long as any other model call on the board gets
COUNTS = {2: "twice", 3: "three times", 4: "four times", 5: "five times"}
SKIP = {"baseline_done", "trained", "recalibrating", "cam_on", "cam_off", "cam_stalled", "drift", "recording",
        "reset", "advice", "router_moved", "router_home", "blind_on", "blind_off", "zone_change", "alert_off"}
CLOCK = re.compile(r"\b\d{1,2}:\d\d (?:AM|PM)\b")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def hm(t_ms: int) -> str:
    """The board's clock time as a person says it: "2:14 AM"."""
    tm = time.localtime(t_ms / 1000)
    return f"{tm.tm_hour % 12 or 12}:{tm.tm_min:02d} {'AM' if tm.tm_hour < 12 else 'PM'}"


def ref(record: dict):
    """The record's number in the sealed chain, or its time (t, epoch ms) when the store does not seal records yet."""
    return record.get("seq") if record.get("seq") is not None else record.get("t")


def where(zone, zones: dict) -> str:
    """" at the desk", " on the left", " in Chair", or "" on one spot whose name is not a place."""
    if zone not in zones:
        return ""
    name = str(zones[zone]).strip()
    if name.split(" ")[0].lower() in ("at", "by", "in", "on"):
        return " " + name[0].lower() + name[1:]
    if len(zones) == 1:
        return ""
    return f" on the {name.lower()}" if name.lower() in ("left", "right") else f" in {name}"


def _device(node, devices: dict) -> str:
    name = devices.get(node)
    if not name:
        return f"The device {node}"
    return name if name.startswith("Pi ") else f"The {name}"


def _seconds(ms: int) -> str:
    s = max(1, round(ms / 1000))
    return "1 second" if s == 1 else f"{s} seconds"


def _dbm(v):
    return round(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _item(t, text, cites):
    return {"t": t, "text": text, "cites": [c for c in cites if c is not None]}


def _visit(enter, leave, seconds, zones, start_t, passed):
    """The sentence for one stay: from an enter (or the start of the stretch) to an exit (or its end)."""
    t0 = enter["t"] if enter else start_t
    t1 = leave["t"] if leave else None
    rows = [r for r in seconds if r["t"] >= t0 // 1000 * 1000 and (t1 is None or r["t"] <= t1)
            and r.get("present") == 1 and r.get("kind") == "person"]
    still = [r for r in rows if r.get("motion") == "still"]
    moving = [r for r in rows if r.get("motion") == "moving"]
    zone = (enter or {}).get("info", {}).get("zone") or (rows[0].get("zone") if rows else None)
    place = where(zone, zones)
    cites = [ref(enter)] if enter else []
    if passed:
        cites += [ref(r) for r in rows] + [ref(leave)] + [ref(p) for p in passed]
        return [_item(t0, f"Somebody walked through{place}.", cites)]
    parts = []
    if len(moving) >= STILL_MIN_S:
        parts.append(f"moved for {_seconds(len(moving) * 1000)}")
    if len(still) >= STILL_MIN_S:
        parts.append(f"stood still for {_seconds(len(still) * 1000)}")
    cites += [ref(r) for r in (moving if len(moving) >= STILL_MIN_S else []) + (still if len(still) >= STILL_MIN_S else [])]
    came = "Somebody stepped in" if enter else "Somebody was already here"
    out = [_item(t0, f"{came}{place}" + (" and " + " and ".join(parts) if parts else "") + ".", cites)]
    if leave:
        out.append(_item(t1, f"They left after {_seconds(t1 - t0)}." if enter else "They left.", [ref(leave)]))
    return out


def timeline(events: list, seconds: list, zones: dict, devices: dict, from_t: int, to_t: int) -> list:
    """One item {t, text, cites} per thing that happened between from_t and to_t, oldest first."""
    events = sorted((e for e in events if from_t <= e["t"] <= to_t), key=lambda e: e["t"])
    seconds = sorted((r for r in seconds if from_t <= r["t"] <= to_t), key=lambda r: r["t"])
    armed_at = lambda t: bool(next((r["armed"] for r in reversed(seconds) if r["t"] <= t), False))
    items, used = [], set()

    def later(i, kind, test=lambda e: True):
        return next((j for j in range(i + 1, len(events)) if j not in used and events[j]["kind"] == kind
                     and test(events[j])), None)

    first_visit = next((e["kind"] for e in events if e["kind"] in ("enter", "exit")), None)
    if seconds and seconds[0].get("present") == 1 and seconds[0].get("kind") == "person" and first_visit != "enter":
        j = next((k for k, e in enumerate(events) if e["kind"] == "exit"), None)
        if j is not None:
            used.add(j)
        items += _visit(None, events[j] if j is not None else None, seconds, zones, seconds[0]["t"], [])

    for i, e in enumerate(events):
        if i in used or e["kind"] in SKIP:
            continue
        kind, info = e["kind"], e.get("info") or {}
        if kind == "enter":
            j = later(i, "exit")
            leave = events[j] if j is not None else None
            passed = []
            if leave is not None:
                used.add(j)
                k = later(i, "passed_by", lambda p: leave["t"] - 1000 <= p["t"] <= leave["t"] + PASSED_GAP_MS)
                if k is not None:
                    used.add(k)
                    passed = [events[k]]
            items += _visit(e, leave, seconds, zones, from_t, passed)
        elif kind == "exit":
            items.append(_item(e["t"], "Somebody left.", [ref(e)]))
        elif kind == "passed_by":
            items.append(_item(e["t"], f"Somebody walked through{where(info.get('zone'), zones)}.", [ref(e)]))
        elif kind == "alert_on":
            j = later(i, "alert_off")
            text = "The no-movement alert went on" + where(info.get("zone"), zones)
            if j is not None:
                used.add(j)
                text += f" and cleared {_seconds(events[j]['t'] - e['t'])} later"
            items.append(_item(e["t"], text + ".", [ref(e)] + ([ref(events[j])] if j is not None else [])))
        elif kind == "checkin":
            items.append(_item(e["t"], "A check-in was received.", [ref(e)]))
        elif kind == "armed":
            items.append(_item(e["t"], "The space was armed.", [ref(e)]))
        elif kind == "disarmed":
            items.append(_item(e["t"], "The space was disarmed.", [ref(e)]))
        elif kind == "intrusion":
            place = where(info.get("zone"), zones) if "zone" in info else f" on the path {info.get('link')}"
            items.append(_item(e["t"], f"An intrusion alert went off{place}.", [ref(e)]))
        elif kind == "tamper":
            node = info.get("node")
            j = later(i, "tamper_cleared", lambda c: (c.get("info") or {}).get("node") == node)
            text = f"{_device(node, devices)} went quiet"
            if j is not None:
                used.add(j)
                text += f" for {_seconds(events[j]['t'] - e['t'])}"
            if armed_at(e["t"]):
                text += " while the space was armed"
            if j is None:
                text += " and had not come back by the end of this stretch"
            items.append(_item(e["t"], text + ".", [ref(e)] + ([ref(events[j])] if j is not None else [])))
        elif kind == "tamper_cleared":
            items.append(_item(e["t"], f"{_device(info.get('node'), devices)} came back.", [ref(e)]))
        elif kind == "object_on":
            j = later(i, "object_off")
            text = "Something was left in the Wi-Fi line" if len(zones) == 1 else "An object appeared"
            if j is not None:
                used.add(j)
                text += f" and was taken away {_seconds(events[j]['t'] - e['t'])} later"
            items.append(_item(e["t"], text + ".", [ref(e)] + ([ref(events[j])] if j is not None else [])))
        elif kind == "object_off":
            items.append(_item(e["t"], "The thing in the way was taken away.", [ref(e)]))
        elif kind == "advice_result":
            before, after = _dbm(info.get("before_dbm")), _dbm(info.get("after_dbm"))
            if before is not None and after is not None:
                items.append(_item(e["t"], f"The Wi-Fi signal went from {before} to {after} dBm.", [ref(e)]))
        elif kind == "witness_silent":
            items.append(_item(e["t"], f"{_device(info.get('node'), devices)} stopped signing the record.", [ref(e)]))
        elif kind == "witness_back":
            items.append(_item(e["t"], f"{_device(info.get('node'), devices)} signed the record again.", [ref(e)]))
    return merge(sorted(items, key=lambda it: it["t"]))


def merge(items: list) -> list:
    """The same sentence twice in a row in the same minute is said once, with how many times."""
    out = []
    for it in items:
        last = out[-1] if out else None
        if last and last["base"] == it["text"] and hm(last["t"]) == hm(it["t"]) and "walked through" in it["text"]:
            last["n"] += 1
            last["cites"] += it["cites"]
            last["text"] = last["base"][:-1] + " " + COUNTS.get(last["n"], f"{last['n']} times") + "."
        else:
            out.append({**it, "cites": list(it["cites"]), "base": it["text"], "n": 1})
    return [{"t": it["t"], "text": it["text"], "cites": it["cites"]} for it in out]


def tell(items: list) -> str:
    """The sentences in order, each minute's clock time said once before its sentences."""
    parts, said = [], None
    for it in items:
        if hm(it["t"]) != said:
            said = hm(it["t"])
            parts.append(f"{said}.")
        parts.append(it["text"])
    return " ".join(parts)


def nothing(seconds: list, from_t: int, to_t: int) -> str:
    """What to say for a stretch with nothing in it, from what was saved."""
    span = f"between {hm(from_t)} and {hm(to_t)}"
    if not seconds:
        return f"I have no records {span}."
    unknown = sum(r.get("present") is None for r in seconds)
    text = f"Nothing happened {span}. Nobody was seen."
    if unknown:
        text += f" For {_seconds(unknown * 1000)} of it the sensor could not tell."
    return text


def _facts(text: str):
    times = CLOCK.findall(text)
    rest = CLOCK.sub(" ", text)
    return sorted(times), sorted(NUMBER.findall(rest))


def problem(written: str, template: str):
    """Why the model's wording can't replace the template story, or None if it can."""
    written = " ".join(str(written).split())
    if not written:
        return "empty"
    if len(written.split()) > len(template.split()) * 3 // 2 + 10:
        return "too long"
    bad = BANNED.search(written)
    if bad and not BANNED.search(template):
        return f"a word we never use ({bad.group(0)})"
    if _facts(written) != _facts(template):
        return "a time or a number changed, added or dropped"
    return None


def messages(template: str) -> list:
    return [{"role": "system", "content":
             "You smooth the wording of a short story told by a room sensor. Keep every sentence, every clock "
             "time and every number exactly as written, in the same order. Add nothing. Call a person somebody. "
             "Reply with the story only."},
            {"role": "user", "content": template}]


def smooth(template: str, llm, timeout_s: float = SMOOTH_TIMEOUT_S) -> tuple:
    """(text, where it came from): the model's wording when `problem` finds nothing, else the template."""
    if llm is None:
        return template, "template"
    try:
        written = " ".join(str(within(timeout_s, llm, messages(template))).split())
    except Exception as e:   # slow, down, or a reply we can't read
        return template, f"template ({e or type(e).__name__})"
    why = problem(written, template)
    return (written, "llm") if why is None else (template, f"template ({why})")
