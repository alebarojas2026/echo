"""What each line did in a set of one-spot recordings, as a table.

    python -m lab.gate_lines <folder> <plan.json> --which tune
    python -m lab.gate_lines <folder> <plan.json> --which all --text-line "laptop=<folder of .txt files>"

The plan is lab/gate_tune.py's. One row per run and line:

    per s         readings a second
    quiet         the line's level in the run's baseline (median, dBm), and how far its readings spread
                  there (one standard deviation, dB)
    person        how far the session's median fell under that level with somebody on the spot:
                  smallest / median / largest over the sessions
    worst second  the smallest 1 s median fall inside any of those sessions (standing: "person" and
                  "still"); "moving worst" is the same for the sessions where the person stepped about
    empty dip     the largest 1 s median fall in any empty session of the run (drift counts)
    gap           the smallest person fall minus the largest empty dip; "by the second" takes the
                  worst second in place of the smallest session
    2 s spread    the standard deviation of the readings in 2 s windows (median, and the 10th to 90th
                  percentile) for empty, still and moving sessions

--which tune leaves the held-out sessions unread, so the table can be looked at while settings
are still being chosen. --text-line adds a line read by another device as text files of
"<epoch seconds> <dBm>" lines: empty60.txt is its baseline, personN.txt and emptyN.txt its rounds.

It prints markdown and writes nothing. The numbers describe recordings; PROOF.md's rows come
from the proof pipeline, not from here.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Dict, List

from lab.gate_tune import NOBODY, read_rssi

LINES = ("pi5>pi5b:wifi", "pi5b>unoq:ble", "pi5b>pi5:ble")
STANDING = ("person", "still")   # somebody standing on the spot; "moving" steps about and is counted apart
SPREAD_MIN = 8   # readings a 2 s spread needs (brain/features.py LONG_MIN)


def medians(pts: List[tuple], window_ms: int = 1000, hop_ms: int = 500) -> List[float]:
    """The medians of the readings in each window that has two or more."""
    if not pts:
        return []
    out, t, end = [], pts[0][0], pts[-1][0]
    while t + window_ms <= end + hop_ms:
        v = [d for at, d in pts if t <= at < t + window_ms]
        if len(v) >= 2:
            out.append(statistics.median(v))
        t += hop_ms
    return out


def spreads(pts: List[tuple], window_ms: int = 2000, hop_ms: int = 500) -> List[float]:
    out, t = [], pts[0][0] if pts else 0
    while pts and t + window_ms <= pts[-1][0] + hop_ms:
        v = [d for at, d in pts if t <= at < t + window_ms]
        if len(v) >= SPREAD_MIN:
            out.append(statistics.pstdev(v))
        t += hop_ms
    return out


def describe(sessions: List[dict]) -> dict:
    """sessions: [{"is", "pts": [(t_ms, dbm)], "base": True for the baseline stretch}] of one line in one run."""
    base = [d for s in sessions if s.get("base") for _, d in s["pts"]]
    if not base:
        return {}
    level = statistics.median(base)
    seconds = sum((s["pts"][-1][0] - s["pts"][0][0]) / 1000 for s in sessions if len(s["pts"]) > 1)
    out = {"per_s": round(sum(len(s["pts"]) for s in sessions) / max(seconds, 1), 1), "quiet_dbm": level,
           "quiet_sd": round(statistics.pstdev(base), 2)}
    falls = [level - statistics.median(d for _, d in s["pts"]) for s in sessions if s["is"] in STANDING and s["pts"]]
    worst = [level - m for s in sessions if s["is"] in STANDING for m in medians(s["pts"])]
    moving = [level - m for s in sessions if s["is"] == "moving" for m in medians(s["pts"])]
    if moving:
        out["moving_worst_second"] = round(min(moving), 1)
    dips = [level - m for s in sessions if s["is"] in NOBODY or s.get("base") for m in medians(s["pts"])]
    out["rounds"] = len(falls)
    if falls:
        out["person"] = [round(min(falls), 1), round(statistics.median(falls), 1), round(max(falls), 1)]
        out["worst_second"] = round(min(worst), 1)
    out["empty_dip"] = round(max(dips), 1) if dips else None
    if falls and dips:
        out["gap"] = round(min(falls) - max(dips), 1)
        out["gap_second"] = round(min(worst) - max(dips), 1)
    for name, kinds in (("empty", NOBODY + ("baseline",)), ("still", ("still", "person")), ("moving", ("moving",))):
        v = sorted(x for s in sessions if s["is"] in kinds for x in spreads(s["pts"]))
        if v:
            out[f"spread_{name}"] = [round(statistics.median(v), 2), round(v[len(v) // 10], 2), round(v[(len(v) * 9) // 10], 2)]
    for s in sessions:
        if s["is"] in ("walk", "side", "behind", "thing") and s["pts"]:
            m = medians(s["pts"], 500, 100)
            out.setdefault("checks", {})[f'{s["is"]} ({s["name"]})'] = \
                {"deepest_half_second": round(level - min(m), 1), "median": round(level - statistics.median(m), 1)}
    return out


def from_plan(folder, plan: dict, which: str) -> Dict[str, Dict[str, dict]]:
    out: Dict[str, Dict[str, dict]] = {}
    for run in plan["runs"]:
        chosen = [s for s in run["sessions"] if which == "all" or s["set"] == which]
        first = run["sessions"][0]
        if not chosen or (which != "all" and first["set"] != which):
            continue
        read = {s["session"]: read_rssi(Path(folder) / f'{s["session"]}.jsonl') for s in chosen}
        for line in LINES:
            rows = []
            for s in chosen:
                pts = [(t, d) for t, link, d in read[s["session"]] if link == line]
                if s is first:
                    cut = pts[0][0] + int(run.get("baseline_s", 1e9) * 1000) if pts else 0
                    rows.append({"is": "baseline", "base": True, "pts": [p for p in pts if p[0] < cut], "name": s["session"]})
                    pts = [p for p in pts if p[0] >= cut]
                if pts and s["is"] != "baseline":
                    rows.append({"is": s["is"], "pts": pts, "name": s["session"]})
            out.setdefault(run["id"], {})[line] = describe(rows)
    return out


def from_text(folder, rounds=None) -> dict:
    """A line kept as text files: empty60.txt (the baseline), personN.txt and emptyN.txt."""
    rows = []
    for path in sorted(Path(folder).glob("*.txt")):
        name = path.stem
        n = "".join(c for c in name if c.isdigit())
        kind = name.rstrip("0123456789")
        if name != "empty60" and rounds is not None and (not n or int(n) not in rounds):
            continue
        pts = []
        for text in path.read_text(encoding="utf-8").splitlines():
            a = text.split()
            if len(a) == 2:
                pts.append((int(float(a[0]) * 1000), float(a[1])))
        rows.append({"is": "baseline" if name == "empty60" else kind, "base": name == "empty60", "pts": pts, "name": name})
    return describe(rows)


def markdown(tables: Dict[str, Dict[str, dict]]) -> str:
    def three(v):
        return "" if not v else f"{v[0]} / {v[1]} / {v[2]}"

    def spread(v):
        return "" if not v else f"{v[0]} ({v[1]} to {v[2]})"

    out = ["| run | line | per s | quiet dBm (sd) | rounds | person fall min / med / max | worst second | moving worst | empty dip "
           "| gap | gap by the second | 2 s spread empty | still | moving |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    checks = []
    for run, lines in tables.items():
        for line, d in lines.items():
            if not d:
                continue
            out.append(f'| {run} | `{line}` | {d["per_s"]} | {d["quiet_dbm"]} ({d["quiet_sd"]}) | {d["rounds"]} '
                       f'| {three(d.get("person"))} | {d.get("worst_second", "")} | {d.get("moving_worst_second", "")} | {d.get("empty_dip", "")} '
                       f'| {d.get("gap", "")} | {d.get("gap_second", "")} | {spread(d.get("spread_empty"))} '
                       f'| {spread(d.get("spread_still"))} | {spread(d.get("spread_moving"))} |')
            for name, c in (d.get("checks") or {}).items():
                checks.append(f'| {run} | `{line}` | {name} | {c["deepest_half_second"]} | {c["median"]} |')
    if checks:
        out += ["", "| run | line | check | deepest 0.5 s median fall | median fall |", "|---|---|---|---|---|"] + checks
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A per-line table of one-spot recordings.")
    ap.add_argument("folder")
    ap.add_argument("plan")
    ap.add_argument("--which", choices=("tune", "heldout", "all"), default="tune")
    ap.add_argument("--text-line", action="append", default=[], metavar="NAME=FOLDER")
    ap.add_argument("--text-rounds", default="", help="only these rounds of a text line, e.g. 1-5")
    args = ap.parse_args(argv)
    tables = from_plan(args.folder, json.loads(Path(args.plan).read_text(encoding="utf-8")), args.which)
    rounds = None
    if args.text_rounds:
        a, _, b = args.text_rounds.partition("-")
        rounds = set(range(int(a), int(b or a) + 1))
    for pair in args.text_line:
        name, _, folder = pair.partition("=")
        tables.setdefault("text files", {})[name] = from_text(folder, rounds)
    print(markdown(tables))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
