"""Gate 8: read a recorded wave session and show what the check-in rule makes of it.

    python -m brain.tune_checkin data/sessions/gate8-wave.jsonl --waves 12 19 26.5 --walk-from 80

--waves are the seconds into the recording (from its meta line) at which each wave began;
--wave-s is how long a wave lasts (default 2.5). --walk-from is where the plain walking part
starts; without it, everything outside the waves counts as "no wave".

It prints, for a real recording only (src live; --allow-sim for a dry run of the tool):
- per wave: how many pi5>unoq:wifi readings sat at least 1.5 dB above and below the 1 s
  rolling median, the biggest swing each way, and whether today's rule checked in;
- check-ins outside the waves, per minute;
- the same two counts for a grid of settings, best first, so the constants in
  brain/alert.py can be set from the recording (issue #223).

The replay has no decisions in it, so "pred.zone unchanged" is taken as true. Nothing here
writes a number anywhere: it prints, and a person decides.
"""
from __future__ import annotations

import argparse
import itertools
import statistics
from collections import deque
from typing import Dict, List, Optional

from brain.alert import CHECKIN_LINK, CROSS_DB, CROSS_WINDOW_MS, CROSSINGS, MEDIAN_MS, OTHER_LINK_DB, CheckIn
from brain.core import last_meta, read_session

GRID = {"cross_db": (1.0, 1.5, 2.0, 2.5, 3.0), "crossings": (2, 3, 4, 5, 6),
        "window_ms": (1500, 2500, 3500), "other_db": (3.0, 6.0, None)}


def swings(readings: List[tuple], t0: int, t1: int, cross_db: float = CROSS_DB) -> dict:
    """What the check-in link did in [t0, t1): readings at least cross_db above and below the
    1 s rolling median, and the biggest swing each way (dB)."""
    recent: deque = deque()
    above = below = n = 0
    up = down = 0.0
    for t, dbm in readings:
        recent.append((t, dbm))
        while recent[0][0] <= t - MEDIAN_MS:
            recent.popleft()
        if not t0 <= t < t1:
            continue
        dev = dbm - statistics.median(d for _, d in recent)
        n += 1
        above += dev >= cross_db
        below += dev <= -cross_db
        up, down = max(up, dev), min(down, dev)
    return {"readings": n, "above": above, "below": below, "max_up_db": round(up, 1), "max_down_db": round(down, 1)}


def replay(messages: List[dict], **rule) -> List[int]:
    """The recv_t of every check-in the rule finds in a recording."""
    check, out = CheckIn(**rule), []
    for m in messages:
        if m.get("type") == "rssi" and check.push(m["recv_t"], m["link"], float(m["dbm"])):
            out.append(m["recv_t"])
    return out


def tally(fired: List[int], waves: List[tuple], quiet: List[tuple]) -> dict:
    """Waves caught (a check-in from its start to 1 s after its end) and check-ins in the quiet spans."""
    caught = sum(any(a <= t < b + 1000 for t in fired) for a, b in waves)
    false = sum(any(a <= t < b for a, b in quiet) for t in fired)
    minutes = sum(b - a for a, b in quiet) / 60_000
    return {"caught": caught, "waves": len(waves), "false": false,
            "false_per_min": round(false / minutes, 2) if minutes > 0 else None}


def spans(start: int, end: int, wave_starts_s: List[float], wave_s: float, walk_from_s: Optional[float]):
    """(wave spans, quiet spans) in recv_t ms. Quiet = outside every wave (with 1 s kept clear after each)."""
    waves = [(start + int(s * 1000), start + int((s + wave_s) * 1000)) for s in sorted(wave_starts_s)]
    t, quiet = start if walk_from_s is None else start + int(walk_from_s * 1000), []
    for a, b in waves:
        if a > t:
            quiet.append((t, a))
        t = max(t, b + 1000)
    if end > t:
        quiet.append((t, end))
    return waves, quiet


def grid(messages, waves, quiet) -> List[dict]:
    rows = []
    for cross_db, crossings, window_ms, other_db in itertools.product(*GRID.values()):
        rule = {"cross_db": cross_db, "crossings": crossings, "window_ms": window_ms, "other_db": other_db}
        rows.append({**rule, **tally(replay(messages, **rule), waves, quiet)})
    return sorted(rows, key=lambda r: (-(r["caught"] - r["false"]), r["false"], -r["caught"]))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session", help="a bus session file with the waves in it")
    ap.add_argument("--waves", type=float, nargs="+", required=True, help="seconds into the recording, one per wave")
    ap.add_argument("--wave-s", type=float, default=2.5)
    ap.add_argument("--walk-from", type=float, default=None, help="seconds into the recording where plain walking starts")
    ap.add_argument("--top", type=int, default=12, help="grid rows to print")
    ap.add_argument("--allow-sim", action="store_true", help="try the tool on a sim file; says nothing about the rule")
    args = ap.parse_args(argv)

    meta = last_meta(args.session)
    messages = read_session(args.session, meta.get("recv_t") if meta else None)
    rssi = [m for m in messages if m.get("type") == "rssi"]
    wifi = [(m["recv_t"], float(m["dbm"])) for m in rssi if m.get("link") == CHECKIN_LINK]
    if not wifi:
        raise SystemExit(f"no {CHECKIN_LINK} readings in {args.session}")
    if any(m.get("src") != "live" for m in rssi):
        if not args.allow_sim:
            raise SystemExit("this file is not a live recording; thresholds are set from real waves only")
        print("NOT A MEASUREMENT: sim or replay data, for trying the tool only")
    start = meta["recv_t"] if meta and meta.get("recv_t") is not None else messages[0]["recv_t"]
    waves, quiet = spans(start, messages[-1]["recv_t"], args.waves, args.wave_s, args.walk_from)
    seconds = (wifi[-1][0] - wifi[0][0]) / 1000 or 1
    print(f"{CHECKIN_LINK}: {len(wifi)} readings, {len(wifi) / seconds:.1f} a second")

    now = replay(messages)
    print(f"\nper wave (+/-{CROSS_DB} dB around the 1 s median):")
    for i, (a, b) in enumerate(waves, 1):
        s = swings(wifi, a, b)
        hit = any(a <= t < b + 1000 for t in now)
        print(f"  wave {i:2d} at {(a - start) / 1000:6.1f} s: {s['above']:3d} above, {s['below']:3d} below of {s['readings']:3d}; "
              f"max +{s['max_up_db']} / {s['max_down_db']} dB; check-in: {'yes' if hit else 'no'}")
    t = tally(now, waves, quiet)
    print(f"\ntoday's rule ({CROSS_DB} dB, {CROSSINGS} crossings, {CROSS_WINDOW_MS} ms, other links {OTHER_LINK_DB} dB): "
          f"{t['caught']} of {t['waves']} waves, {t['false']} check-ins outside them ({t['false_per_min']} a minute)")
    print(f"\ngrid, best {args.top} (other_db None = other links not checked):")
    for r in grid(messages, waves, quiet)[:args.top]:
        print(f"  {r['cross_db']} dB, {r['crossings']} crossings, {r['window_ms']} ms, other {r['other_db']}: "
              f"{r['caught']} of {r['waves']} waves, {r['false']} outside ({r['false_per_min']} a minute)")


if __name__ == "__main__":
    main()
