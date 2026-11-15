"""The detective: "what happened?" answered from the stored records only (issue #866, section 4).

It runs a few small tools in order and times each one:
    fetch events -> fetch summaries -> line up the timeline -> verify the chain -> write the story
The story is built by narrator/story.py's templates from the rows. The on-board model is never waited on
here: it may only smooth the wording when a writer is passed (python -m agent.ask --smooth), and its text
is used only when every time and number is kept exactly. The answer carries `steps`, `cites` and `chain_ok`.

The chain check goes through `verify(store, from_seq, to_seq)` below, which calls the store's own verify
function (the sealed record, #866 section 1) when the store has one. A store that does not seal records
yet has no `seq`: then there is no `cites` or `chain_ok`, and each sentence row cites its records by time
("t" and the epoch ms, e.g. "t1763149515000").
"""
import math
import re
import time

from narrator import story

JUST_MIN = 2   # "what just happened"


def verify(store, from_seq, to_seq) -> dict:
    """{"ok": bool or None, "checked": n, "first_bad_seq": k or None} over from_seq..to_seq, from the store's
    own verify function (GET /chain/verify's shape). ok is None when the store keeps no chain."""
    fn = getattr(store, "verify", None)
    if not callable(fn) or from_seq is None:
        return {"ok": None, "checked": 0, "first_bad_seq": None}
    out = fn(from_seq, to_seq)
    if isinstance(out, bool):
        out = {"ok": out}
    out = dict(out or {})
    ok = out.get("ok")
    return {"ok": ok if isinstance(ok, bool) else False, "checked": int(out.get("checked") or 0),
            "first_bad_seq": out.get("first_bad_seq")}


H = r"(\d{1,2})(?::(\d\d))?\s*(am|pm|a\.m\.|p\.m\.)?"
BETWEEN = re.compile(r"\b(?:between|from)\s+" + H + r"\s+(?:and|to|till|until|-)\s+" + H, re.I)


def _clock_options(h, mm, ampm):
    if h > 23 or mm > 59:
        return None
    t = h * 60 + mm
    ampm = (ampm or "").replace(".", "").lower()
    if ampm == "pm" and h < 12:
        t += 720
    if ampm == "am" and h == 12:
        t -= 720
    return [t] if ampm or h > 12 or h == 0 else [t, t + 720]


def between_said(question: str, now_ms: int):
    """(from_t, to_t) for "between 2:10 and 2:20" (the latest such stretch up to now), or None."""
    m = BETWEEN.search(question)
    if not m:
        return None
    a = _clock_options(int(m.group(1)), int(m.group(2) or 0), m.group(3) or m.group(6))
    b = _clock_options(int(m.group(4)), int(m.group(5) or 0), m.group(6))
    if not a or not b:
        return None
    tm = time.localtime(now_ms / 1000)
    midnight = now_ms - ((tm.tm_hour * 60 + tm.tm_min) * 60 + tm.tm_sec) * 1000 - now_ms % 1000
    day = 1440 * 60_000
    ends = sorted(midnight + o * 60_000 + d for o in b for d in (0, -day) if midnight + o * 60_000 + d <= now_ms + 60_000)
    if not ends:
        return None
    to_t = ends[-1] + 59_999          # "until 2:20" takes in the whole of 2:20
    starts = sorted(midnight + o * 60_000 + d for o in a for d in (0, -day) if midnight + o * 60_000 + d <= to_t)
    return (starts[-1], min(to_t, now_ms)) if starts else None


def window(question: str, now_ms: int, minutes_said):
    """(from_t, to_t, minutes) of the stretch the question asks about."""
    span = between_said(question, now_ms)
    if span:
        return span[0], span[1], max(1, min(1440, math.ceil((span[1] - span[0]) / 60_000)))
    said = minutes_said(question, time.localtime(now_ms / 1000)[3:5])
    if said is None:
        said = JUST_MIN if re.search(r"\bjust (happen|went on)", question, re.I) else 10
    return now_ms - said * 60_000, now_ms, said


def investigate(store, from_t: int, to_t: int, zones: dict, devices: dict, writer=None, timer=time.perf_counter) -> dict:
    """{"answer", "rows", "steps", "span"}, and "cites" and "chain_ok" when the records are sealed."""
    steps = []

    def step(tool, fn):
        start = timer()
        out = fn()
        steps.append({"tool": tool, "ms": round((timer() - start) * 1000, 2), "rows": None})
        return out

    events = step("fetch events", lambda: [e for e in store.events(from_t) if e["t"] <= to_t])
    steps[-1]["rows"] = len(events)
    seconds = step("fetch summaries", lambda: store.seconds(from_t, to_t))
    steps[-1]["rows"] = len(seconds)
    items = step("line up the timeline", lambda: story.timeline(events, seconds, zones, devices, from_t, to_t))
    steps[-1]["rows"] = len(items)
    cited = sorted({c for it in items for c in it["cites"] if isinstance(c, int)})
    seqs = cited or sorted(r["seq"] for r in events + seconds if r.get("seq") is not None)
    chain = step("verify the chain", lambda: verify(store, seqs[0] if seqs else None, seqs[-1] if seqs else None))
    steps[-1]["rows"] = chain["checked"]

    def write():
        text = story.tell(items) if items else story.nothing(seconds, from_t, to_t)
        return story.smooth(text, writer)[0] if items and writer is not None else text
    text = step("write the story" if writer is None else "write the story and smooth it", write)
    steps[-1]["rows"] = len(items)
    if chain["ok"] is False:
        bad = chain["first_bad_seq"]
        text = (f"Warning: the sealed record does not check out at record {bad}, so this story can't be trusted "
                "from there on. " if bad is not None else
                "Warning: the sealed record does not check out, so this story can't be trusted. ") + text
    rows = [{"row": "sentence", "at": story.hm(it["t"]), "t": it["t"], "text": it["text"], "cites": it["cites"]}
            for it in items]
    rows.append({"row": "chain", "ok": chain["ok"], "checked": chain["checked"], "first_bad_seq": chain["first_bad_seq"],
                 "from": story.hm(from_t), "to": story.hm(to_t)})
    out = {"answer": text, "rows": rows, "steps": steps, "span": {"from_t": from_t, "to_t": max(from_t, to_t)}}
    if chain["ok"] is not None:   # section 13: cites and chain_ok only when there is a sealed record to check
        out.update(cites=cited, chain_ok=chain["ok"])
    return out
