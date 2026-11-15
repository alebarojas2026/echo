"""A rough range for a beacon nobody has placed yet, from how strongly each receiver hears it.

When a hall beacon is heard that has no position in radio/nodes.json, the screen can show it
somewhere sensible instead of nowhere, as a hint for placing it by hand. This is an ESTIMATE
from signal strength and nothing else. It is never a measured position.

The model is the plain log-distance one: a beacon heard at P dBm is about

    d = 10 ^ ((AT_1M_DBM - P) / (10 * n)) metres away,

where AT_1M_DBM is what such a beacon reads at 1 m and n says how fast a signal fades with
distance. Neither is measured here: AT_1M_DBM = -59 is the usual figure for a small Bluetooth
beacon, and n is taken between 2.0 (open air) and 3.0 (a hall with people and furniture). The
answer carries both ends: the estimate at n = 2.5, the nearest it could be at n = 3.0 and the
farthest at n = 2.0. At -85 dBm that is 11 m, between 7 and 20 m. That width is the honest
part of the answer, and both assumptions travel with it in the output.

Rules:
- The level used is the median of the last 10 s of each receiver's readings, and a receiver
  needs 10 s of them (first to last reading at least 8 s apart, and 10 or more readings). In a
  full hall single readings swing by 10 dB; a median over 10 s does not.
- "unknown" (None) rather than a jumpy guess: when no receiver has enough readings, when a
  receiver's own readings are too spread out (the middle half of them wider than 8 dB), or
  when the receivers disagree by more than 10 dB among themselves. Our receivers sit within
  about a metre of each other, so from 10 m away they should all hear much the same level; if
  they don't, something is in the way of one of them and no single range is right.
- The receivers are combined by taking the median of their levels. Three receivers a metre
  apart can't give a direction to something 10 to 25 m away, so there is no bearing: only a range.

Nothing here touches the core links, and nothing is learned.

    ranges = Ranges()
    ranges.add("h", "unoq", recv_t_ms, dbm)     # every reading of a hall link
    ranges.estimate("h", now_ms)                # {"m": 11.2, "lo_m": 7.4, "hi_m": 20.0, ...} or None
"""
from __future__ import annotations

import statistics
from collections import deque
from typing import Dict, Optional

AT_1M_DBM = -59.0          # assumed: what a small Bluetooth beacon reads at 1 m
EXPONENT = 2.5             # assumed: how fast the signal fades with distance (the estimate)
EXPONENT_NEAR, EXPONENT_FAR = 3.0, 2.0   # ... and the ends of the range: a cluttered hall, open air
WINDOW_MS = 10_000         # the level is the median over this long
MIN_SPAN_MS = 8_000        # ... and needs readings from at least this much of it
MIN_READINGS = 10
MAX_SPREAD_DB = 8.0        # a receiver whose middle half of readings is wider than this is not steady enough
MAX_DISAGREE_DB = 10.0     # receivers a metre apart that differ by more than this don't give one range
MAX_M = 100.0              # past this a Bluetooth beacon isn't heard at all; the far end is capped here


def metres(dbm: float, exponent: float = EXPONENT) -> float:
    """The log-distance model: how far a beacon heard at `dbm` is, for a given fading exponent."""
    return 10 ** ((AT_1M_DBM - dbm) / (10 * exponent))


class Ranges:
    def __init__(self):
        self._readings: Dict[str, Dict[str, deque]] = {}   # beacon -> receiver -> (recv_t, dbm), the last 10 s

    def add(self, beacon: str, receiver: str, t: int, dbm: float) -> None:
        q = self._readings.setdefault(beacon, {}).setdefault(receiver, deque())
        q.append((int(t), float(dbm)))
        while q and q[0][0] <= t - WINDOW_MS:
            q.popleft()

    def _level(self, q: deque, now: int) -> Optional[float]:
        """One receiver's steady level over the last 10 s, or None when it has too little or is too spread out."""
        values = [d for t, d in q if 0 <= now - t < WINDOW_MS]
        times = [t for t, _ in q if 0 <= now - t < WINDOW_MS]
        if len(values) < MIN_READINGS or times[-1] - times[0] < MIN_SPAN_MS:
            return None
        q1, _, q3 = statistics.quantiles(values, n=4)
        if q3 - q1 > MAX_SPREAD_DB:
            return None
        return statistics.median(values)

    def estimate(self, beacon: str, now: int) -> Optional[dict]:
        """The rough range of a beacon, or None for "unknown". Never a position, never a bearing."""
        levels = {}
        for receiver, q in (self._readings.get(beacon) or {}).items():
            level = self._level(q, now)
            if level is not None:
                levels[receiver] = level
        if not levels or max(levels.values()) - min(levels.values()) > MAX_DISAGREE_DB:
            return None
        dbm = statistics.median(levels.values())
        return {"m": round(min(MAX_M, metres(dbm)), 1),
                "lo_m": round(min(MAX_M, metres(dbm, EXPONENT_NEAR)), 1),
                "hi_m": round(min(MAX_M, metres(dbm, EXPONENT_FAR)), 1),
                "from": sorted(levels),                      # the receivers it was heard by
                "assumes": {"at_1m_dbm": AT_1M_DBM, "exponent": [EXPONENT_FAR, EXPONENT_NEAR]}}
