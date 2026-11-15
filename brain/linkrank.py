"""Which links see a person: rank every link by how well it tells "someone there" from "nobody there".

For placing the devices. Record a few short blocks, some with the area empty and some with one
person standing in it, and this says which links change, by how much, and whether the change is
more than the same link moves by itself between two empty blocks. No baseline and no model needed.

    # record the blocks now, one after the other (the bus must be running; Enter starts each block):
    python -m brain.linkrank --capture 20 empty left empty right empty

    # or rank blocks already recorded (a session id in data/sessions, or a path to a .jsonl):
    python -m brain.linkrank empty=flutter-033959 left=flutter-034255 right=flutter-034333 empty=flutter-034452

A block's tag is "empty", or anything else for a block with a person in it: "person", or where
they stood ("left", "right", "middle"). Give at least two empty blocks, one before and one after
the person blocks, and alternate when there is time (empty, left, empty, right, empty): the
difference between the empty blocks is the yardstick every change is held against.

Per link:
    /s        readings a second (the lowest of its blocks)
    empty     its level with nobody there, dBm: the median of the 0.5 s means over the empty blocks
    change    level with a person minus level empty, dB (negative = the person weakens the link);
              with several places, the place that changes it most (the verdict names every place
              that reaches it)
    floor     what the level does with nobody there, dB: the largest difference between two empty
              blocks, and never less than the level can be read to from blocks this long
    x floor   change / floor. Under 1 the change is no more than the link's own drift.
    apart     the share of the person's 1 s windows whose mean lies outside where 90% of the empty
              windows lie (the empty blocks together, so drift between them counts against it)
    spread    change in the spread (std of the 0.5 s means), dB: movement shows here, not in the level
    verdict   clear | weak | no signal | too few readings

Only the standard library, so it runs wherever the bus does.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

SESSIONS = Path(__file__).resolve().parent.parent / "data" / "sessions"

BIN_MS = 500            # the 0.5 s means (what section 6's steady rule looks at)
WINDOW_MS = 1000        # the classifier's window
MIN_READINGS = 20       # a block with fewer on a link can't place its level
MIN_FLOOR_DB = 0.3      # never claim to read a level closer than this
CLEAR_X = 2.0           # a change this many times the floor ...
CLEAR_APART = 0.75      # ... with this share of the person's windows outside the empty ones = clear
WEAK_X = 1.3
WEAK_APART = 0.4
SPREAD_FLOOR_DB = 0.3
SPREAD_CLEAR_X = 3.0    # the spread of a 20 s block is itself rough, so it has to change by more
SPREAD_WEAK_X = 2.0
SIDE_X = 2.0            # two places differ on a link when their levels are this many floors apart
ORDER = {"clear": 0, "weak": 1, "no signal": 2, "too few readings": 3}


def readings(lines) -> dict:
    """{link: [(recv_t ms, dbm), ...]} from session lines (JSON text). Anything else is skipped."""
    out: dict = {}
    for line in lines:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "rssi" and isinstance(msg.get("dbm"), (int, float)) \
                and isinstance(msg.get("link"), str):
            t = msg.get("recv_t", msg.get("t"))
            if isinstance(t, (int, float)):
                out.setdefault(msg["link"], []).append((t, msg["dbm"]))
    return out


def _means(points, width_ms) -> list:
    """The mean of each width_ms slice that has a reading, from the first reading on."""
    start, slices = points[0][0], {}
    for t, dbm in points:
        slices.setdefault(int((t - start) // width_ms), []).append(dbm)
    return [statistics.fmean(v) for _, v in sorted(slices.items())]


def block_stats(points) -> dict:
    """One link in one block: n, rate, level (median of the 0.5 s means), spread (their std),
    how closely the level is known, and the 1 s window means."""
    points = sorted(points)
    span_s = (points[-1][0] - points[0][0]) / 1000 if len(points) > 1 else 0.0
    half = _means(points, BIN_MS)
    spread = statistics.pstdev(half) if len(half) > 1 else 0.0
    return {"n": len(points),
            "rate": len(points) / span_s if span_s > 0 else 0.0,
            "level": statistics.median(half),
            "spread": spread,
            "level_err": 1.25 * spread / len(half) ** 0.5,   # standard error of a median
            "windows": _means(points, WINDOW_MS)}


def _halves(points) -> list:
    """A block cut in two at its middle, for a floor when there is only one empty block."""
    points = sorted(points)
    mid = (points[0][0] + points[-1][0]) / 2
    return [[p for p in points if p[0] < mid], [p for p in points if p[0] >= mid]]


def _apart(person_windows, empty_windows) -> float:
    """The share of person windows outside the middle 90% of the empty windows."""
    if not person_windows or len(empty_windows) < 2:
        return 0.0
    cuts = statistics.quantiles(empty_windows, n=20, method="inclusive")
    lo, hi = cuts[0], cuts[-1]
    return sum(1 for w in person_windows if w < lo or w > hi) / len(person_windows)


def rank(blocks) -> dict:
    """blocks: [(tag, {link: [(t ms, dbm)]})] in the order they were recorded.

    Returns {"rows": [one dict per link, best first], "tags": the person tags in first-seen order,
             "one_empty": True when the floor had to come from the halves of a single empty block}.
    """
    empties = [b for tag, b in blocks if tag == "empty"]
    tags = list(dict.fromkeys(tag for tag, _ in blocks if tag != "empty"))
    if not empties or not tags:
        raise ValueError("give at least one empty block and one block with a person")
    links = list(dict.fromkeys(link for _, b in blocks for link in b))
    rows = []
    for link in links:
        per = [(tag, block_stats(b[link]) if len(b.get(link, ())) >= 2 else None) for tag, b in blocks]
        rates = [s["rate"] if s else 0.0 for _, s in per]
        row = {"link": link, "rate": min(rates), "places": {}}
        if any(s is None or s["n"] < MIN_READINGS for _, s in per):
            row.update(verdict="too few readings", empty=None, change=None, floor=None, x=None,
                       apart=None, spread=None, by=None, place=None)
            rows.append(row)
            continue
        e = [s for tag, s in per if tag == "empty"]
        floor_blocks = e
        if len(e) == 1:   # one empty block: its two halves stand in for two blocks
            floor_blocks = [block_stats(h) for h in _halves(empties[0][link]) if len(h) >= 2]
        levels = [s["level"] for s in floor_blocks]
        spreads = [s["spread"] for s in floor_blocks]
        empty_level = statistics.median(s["level"] for s in e)
        empty_spread = statistics.median(s["spread"] for s in e)
        empty_windows = [w for s in e for w in s["windows"]]
        drift = max(levels) - min(levels) if len(levels) > 1 else 0.0
        spread_floor = max(max(spreads) - min(spreads) if len(spreads) > 1 else 0.0, SPREAD_FLOOR_DB)
        best = None
        for tag in tags:
            p = [s for t, s in per if t == tag]
            level = statistics.median(s["level"] for s in p)
            repeat = max(s["level"] for s in p) - min(s["level"] for s in p)   # the same place twice
            err = 2 * max([s["level_err"] for s in p] + [s["level_err"] for s in e])
            floor = max(drift, err, MIN_FLOOR_DB)
            change = level - empty_level
            x = abs(change) / floor
            apart = _apart([w for s in p for w in s["windows"]], empty_windows)
            spread = statistics.median(s["spread"] for s in p) - empty_spread
            sx = abs(spread) / spread_floor
            if x >= CLEAR_X and apart >= CLEAR_APART:
                verdict, by = "clear", "level"
            elif sx >= SPREAD_CLEAR_X:
                verdict, by = "clear", "spread"
            elif x >= WEAK_X and apart >= WEAK_APART:
                verdict, by = "weak", "level"
            elif sx >= SPREAD_WEAK_X:
                verdict, by = "weak", "spread"
            else:
                verdict, by = "no signal", None
            place = {"tag": tag, "level": level, "change": change, "floor": floor, "x": x, "apart": apart,
                     "spread": spread, "verdict": verdict, "by": by, "repeat": repeat}
            row["places"][tag] = place
            if best is None or (ORDER[verdict], -x) < (ORDER[best["verdict"]], -best["x"]):
                best = place
        row.update(verdict=best["verdict"], by=best["by"], place=best["tag"], empty=empty_level,
                   change=best["change"], floor=best["floor"], x=best["x"], apart=best["apart"],
                   spread=best["spread"])
        rows.append(row)
    rows.sort(key=lambda r: (ORDER[r["verdict"]], -(r["x"] or 0.0)))
    return {"rows": rows, "tags": tags, "one_empty": len(empties) == 1}


def sides(result, a="left", b="right") -> list:
    """The links on which place a and place b differ: [(link, level at a - level at b, dB)].
    Two places differ on a link when their levels are SIDE_X floors apart, the floor here also
    counting how far the same place moved between two of its own blocks."""
    out = []
    for row in result["rows"]:
        pa, pb = row["places"].get(a), row["places"].get(b)
        if not pa or not pb:
            continue
        floor = max(pa["floor"], pb["floor"], pa["repeat"], pb["repeat"])
        diff = pa["level"] - pb["level"]
        if abs(diff) >= SIDE_X * floor and "clear" in (pa["verdict"], pb["verdict"]):
            out.append((row["link"], diff))
    return out


def table(result) -> str:
    def num(v, fmt):
        return "__" if v is None else format(v, fmt)

    several = len(result["tags"]) > 1
    width = max([len(r["link"]) for r in result["rows"]] + [4])
    lines = [f"{'link':<{width}} {'/s':>5} {'empty':>6} {'change':>7} {'floor':>6} {'x floor':>7} "
             f"{'apart':>6} {'spread':>7}  verdict"]
    for r in result["rows"]:
        verdict = r["verdict"]
        if r["by"] == "spread":
            verdict += " (in the spread: movement)"
        if several and r["place"] and r["verdict"] in ("clear", "weak"):
            verdict += " at " + ", ".join(t for t, p in r["places"].items() if p["verdict"] == r["verdict"])
        apart = "__" if r["apart"] is None else f"{100 * r['apart']:.0f}%"
        lines.append(f"{r['link']:<{width}} {r['rate']:>5.1f} {num(r['empty'], '.1f'):>6} "
                     f"{num(r['change'], '+.1f'):>7} {num(r['floor'], '.1f'):>6} {num(r['x'], '.1f'):>7} "
                     f"{apart:>6} {num(r['spread'], '+.1f'):>7}  {verdict}")
    return "\n".join(lines)


def summary(result) -> str:
    """The lines under the table: which links carry the detection, and left against right."""
    clear = [r["link"] for r in result["rows"] if r["verdict"] == "clear"]
    weak = [r["link"] for r in result["rows"] if r["verdict"] == "weak"]
    if clear:
        first = "Detection is carried by " + ", ".join(clear) + (f" (weak: {', '.join(weak)})" if weak else "") + "."
    elif weak:
        first = ("No link is clear. Weak: " + ", ".join(weak)
                 + ". Move a device so that a line between two of them passes through the person.")
    else:
        first = ("No link tells a person from an empty area: nobody stood on a line between two devices. "
                 "Move a device so that one does.")
    tags = result["tags"]
    if "left" in tags and "right" in tags:
        told = sides(result)
        if told:
            second = "Left and right can be told apart on " + ", ".join(
                f"{link} ({diff:+.1f} dB left against right)" for link, diff in told) + "."
        else:
            second = "Left and right cannot be told apart: no clear link reads differently at the two."
    else:
        second = "Left against right was not tested (tag one block left and one right)."
    out = [first, second]
    if result["one_empty"]:
        out.append("Only one empty block: the floor is from its two halves and is too kind. "
                   "Record a second empty block after the person blocks.")
    return "\n".join(out)


def load(spec: str, sessions=None):
    """"tag=path-or-session" -> (tag, {link: readings})."""
    tag, sep, where = spec.partition("=")
    tag = tag.strip().lower()
    if not sep or not tag or not where:
        raise ValueError(f"{spec!r}: write each block as tag=session, like empty=flutter-033959 or left=a.jsonl")
    path = Path(where)
    if not path.exists():
        path = (sessions or SESSIONS) / f"{where}.jsonl"
    if not path.exists():
        raise ValueError(f"{where}: no such file, and no {path}")
    by_link = readings(path.read_text(encoding="utf-8").splitlines())
    if not by_link:
        raise ValueError(f"{path} has no rssi readings")
    return tag, by_link


def record(tags, seconds, ask=input, say=print) -> list:
    """Record one block per tag through the bus, waiting for Enter before each. Returns the specs."""
    from radio import link_stats   # the bus recording helper; only needed here

    if link_stats.open_recording():
        raise ValueError(f"the bus is recording {link_stats.open_recording()}: stop it first (record_stop)")
    stamp, specs = time.strftime("%H%M%S"), []
    for i, tag in enumerate(tags, 1):
        who = "nobody in the area" if tag == "empty" else f"one person standing still at: {tag}"
        ask(f"block {i} of {len(tags)}: {who}. Enter when ready ")
        session = f"rank-{stamp}-{i}-{tag}"
        say(f"  recording {seconds:g} s as {session}")
        link_stats.capture(session, seconds)
        specs.append(f"{tag}={session}")
    return specs


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="rank the links by how well they tell a person from an empty area")
    ap.add_argument("blocks", nargs="+", metavar="BLOCK",
                    help="tag=session-or-file for recorded blocks, or just tags with --capture. "
                         "A tag is empty, or person / left / right / any place name.")
    ap.add_argument("--capture", type=float, metavar="SECONDS",
                    help="record each block now, this long, through the bus (Enter starts each one)")
    ap.add_argument("--sessions", default=str(SESSIONS), help="where session ids are looked up")
    args = ap.parse_args(argv)
    try:
        specs = args.blocks
        if args.capture:
            if any("=" in b for b in specs):
                ap.error("with --capture give tags only: --capture 20 empty left empty right empty")
            specs = record([b.strip().lower() for b in specs], args.capture)
            print("to print this table again: python -m brain.linkrank " + " ".join(specs))
        blocks = [load(spec, Path(args.sessions)) for spec in specs]
        result = rank(blocks)
    except ValueError as err:
        sys.exit(str(err))
    print(table(result))
    print()
    print(summary(result))


if __name__ == "__main__":
    main()
