"""Read a sweep of the one-spot presence rules and show which settings are safe, and how wide that is.

    python -m lab.gate_pick <out>/presence.jsonl --hold-s 3

A variant is safe when, on every tuning recording: no decision said "somebody" in an empty
stretch (side crossings and standing behind the far device count as empty), nothing was raised
there while armed, every person on the spot was found and let go again, a person standing there
never dropped out, and every walk-through was seen and was a passed_by, not an intrusion, at
the hold asked for.

A safe setting next to an unsafe one is a bad setting. So each safe variant gets its room: the
number of grid steps it can move, along any one axis, before it meets a variant that is not safe
(the end of the grid is not counted against it). The pick is the safe variant with the most room;
among those, the one closest to today's numbers (a setting that need not change should not), then
the fastest. It prints the safe range of each axis around the pick, with the others held at the pick.

It reads a file and prints. It chooses on tuning recordings only: the pick's score there is
flattered by the choosing, and the number to believe is the held-out one (lab.gate_tune --which heldout).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from lab.gate_tune import DEFAULTS


def safe(total: dict, hold_s: float) -> bool:
    h = str(float(hold_s))
    walk = total.get("walk")
    return bool(
        total["false_present_s"] == 0 and total["false_enters"] == 0 and total["false_alarms"][h] == 0
        and total["found"] == total["people"] and total["not_found"] == 0 and total["not_released"] == 0
        and total["dropouts_standing"] == 0
        and (walk is None or (walk["seen"] == walk["passes"] == walk["armed"][h]["passed_by"]
                              and walk["armed"][h]["intrusion"] == 0)))


def speed(total: dict) -> float:
    """Seconds to find plus seconds to let go: from real walk-throughs when there are any, else at the joins."""
    walk = total.get("walk") or {}
    parts = [walk.get("detect_s") if walk.get("detect_s") is not None else total["detect_s"],
             walk.get("release_s") if walk.get("release_s") is not None else total["release_s"]]
    return sum(99.0 if p is None else p for p in parts)


def read(path) -> List[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def study(rows: List[dict], hold_s: float, axes: Optional[List[str]] = None) -> dict:
    axes = axes or [k for k in DEFAULTS if len({r["params"][k] for r in rows}) > 1]
    values = {k: sorted({r["params"][k] for r in rows}) for k in axes}
    by_key: Dict[tuple, dict] = {tuple(r["params"][k] for k in axes): r for r in rows}
    ok = {key: safe(r["total"], hold_s) for key, r in by_key.items()}

    def reach(key, i, step):
        """Grid steps from key along axis i in one direction before an unsafe variant; None = none before the grid ends."""
        at, n = values[axes[i]].index(key[i]), 0
        while True:
            at += step
            if not 0 <= at < len(values[axes[i]]):
                return None
            other = key[:i] + (values[axes[i]][at],) + key[i + 1:]
            if not ok.get(other):
                return n      # not safe, or not a variant at all (the off level would reach the on level)
            n += 1

    def room(key):
        steps = [reach(key, i, step) for i in range(len(axes)) for step in (-1, 1)]
        return min((s for s in steps if s is not None), default=99)

    safe_keys = [k for k, good in ok.items() if good]
    out = {"axes": axes, "values": values, "variants": len(rows), "safe": len(safe_keys), "hold_s": hold_s, "pick": None}
    if not safe_keys:
        return out
    today = tuple(DEFAULTS[k] for k in axes)

    def far(key):   # grid steps from today's numbers, summed over the axes
        return sum(abs(values[a].index(key[i]) - values[a].index(today[i])) if today[i] in values[a] else 1
                   for i, a in enumerate(axes))

    best = max(safe_keys, key=lambda k: (room(k), -far(k), -speed(by_key[k]["total"])))
    out["pick"] = {"params": by_key[best]["params"], "room_steps": room(best), "total": by_key[best]["total"],
                   "speed_s": round(speed(by_key[best]["total"]), 2)}
    out["today"] = None if today not in ok else {"safe": ok[today], "room_steps": room(today) if ok[today] else 0,
                                                 "speed_s": round(speed(by_key[today]["total"]), 2)}
    span = {}
    for i, a in enumerate(axes):
        good = [v for v in values[a] if ok.get(best[:i] + (v,) + best[i + 1:])]
        tried = [v for v in values[a] if best[:i] + (v,) + best[i + 1:] in ok]
        span[a] = {"safe": good, "tried": tried}
    out["span_at_pick"] = span
    out["safe_share_by_value"] = {a: {str(v): round(sum(1 for k in safe_keys if k[i] == v)
                                                    / max(1, sum(1 for k in ok if k[i] == v)), 3) for v in values[a]}
                                  for i, a in enumerate(axes)}
    fastest = min(safe_keys, key=lambda k: speed(by_key[k]["total"]))
    out["fastest_safe"] = {"params": by_key[fastest]["params"], "room_steps": room(fastest),
                           "speed_s": round(speed(by_key[fastest]["total"]), 2)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="The safe region of a one-spot sweep, and the pick in the middle of it.")
    ap.add_argument("file", help="a .jsonl written by lab/gate_sweep.py")
    ap.add_argument("--hold-s", type=float, default=3.0, help="armed.hold_s the walk-throughs are judged at")
    args = ap.parse_args(argv)
    print(json.dumps(study(read(args.file), args.hold_s), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
