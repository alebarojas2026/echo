"""Windows and per-link features (CONTRACTS.md v2, section 6).

Windows are 1.0 s long with a 0.1 s hop, timed on the bus's recv_t (board ms).
Each window covers [end - 1000, end) and window ends sit on the 100 ms grid.

Per link, a window has: n (readings), mean, std, min, max (dBm) and drop_db,
which is base_dbm - mean (positive = the signal fell below the baseline).
The baseline is the per-link median over a 20 s capture.

A window's label is the majority of the non-clipped camera labels in it.
Windows with a clipped label or with no label get label None and are left
out of training.
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, deque
from typing import Dict, Iterable, Iterator, List, Optional

WINDOW_MS = 1000
HOP_MS = 100

# Section 6 object rule: a link drops >= 3 dB for >= 2 s with std < 0.8 dB.
STEADY_MS = 2000
STEADY_DROP_DB = 3.0
STEADY_STD_DB = 0.8
STEADY_BIN_MS = 500    # the std is taken over 0.5 s means, the same way the x-ray does it
STEADY_COVER = 0.9     # readings must span this much of the 2 s

# Classifier links, in the fixed order used for feature vectors (section 3).
LINKS = (
    "pi5>unoq:wifi",
    "pi5>unoq:ble",
    "east>unoq:ble",
    "west>unoq:ble",
    "east>pi5:ble",
    "west>pi5:ble",
)
STATS = ("mean", "std", "min", "max", "drop_db")


def baseline(messages: Iterable[dict]) -> Dict[str, float]:
    """Per-link median dBm over a baseline capture: {link: base_dbm}."""
    by_link: Dict[str, List[float]] = {}
    for m in messages:
        if m.get("type") == "rssi":
            by_link.setdefault(m["link"], []).append(float(m["dbm"]))
    return {link: statistics.median(v) for link, v in by_link.items()}


def link_stats(dbms: List[float], base_dbm: Optional[float]) -> dict:
    """Features of one link in one window. Empty input -> all None, n 0."""
    if not dbms:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None, "drop_db": None}
    mean = sum(dbms) / len(dbms)
    std = math.sqrt(sum((d - mean) ** 2 for d in dbms) / len(dbms))
    return {
        "n": len(dbms),
        "mean": mean,
        "std": std,
        "min": min(dbms),
        "max": max(dbms),
        "drop_db": None if base_dbm is None else base_dbm - mean,
    }


def window_label(labels: List[dict]) -> Optional[dict]:
    """Majority of the camera labels in a window, or None if it is dropped.

    zone is 0 when nobody is present. motion is "moving" / "still" / None.
    """
    if not labels or any(lb.get("clipped") for lb in labels):
        return None
    zones = Counter((lb["zone"] or 0) if lb.get("present") else 0 for lb in labels)
    zone = _majority(zones)
    motions = Counter(lb.get("motion") for lb in labels if lb.get("present"))
    modes = Counter(lb.get("mode") for lb in labels)
    return {
        "zone": zone,
        "present": zone != 0,
        "motion": _majority(motions) if zone != 0 else None,
        "mode": _majority(modes),
        "persons_in_frame": max((lb.get("persons_in_frame") or 0) for lb in labels),
        "n_labels": len(labels),
    }


def steady_drop(readings: List[tuple], base_dbm: Optional[float], end: int) -> bool:
    """The section 6 object rule for one link over the 2 s before `end`.

    readings: (recv_t, dbm) pairs. True when they span the 2 s, their median sits
    >= 3 dB under the baseline, and the std of their 0.5 s means is < 0.8 dB.
    """
    start = end - STEADY_MS
    pts = [(t, d) for t, d in readings if start <= t < end]
    if base_dbm is None or len(pts) < 2 or pts[-1][0] - pts[0][0] < STEADY_COVER * STEADY_MS:
        return False
    bins: Dict[int, List[float]] = {}
    for t, d in pts:
        bins.setdefault((t - start) // STEADY_BIN_MS, []).append(d)
    means = [sum(v) / len(v) for v in bins.values()]
    if len(means) < 2 or statistics.pstdev(means) >= STEADY_STD_DB:
        return False
    return base_dbm - statistics.median(d for _, d in pts) >= STEADY_DROP_DB


def _majority(counts: Counter):
    """Most common value; ties go to the value seen first (Counter order)."""
    return counts.most_common(1)[0][0] if counts else None


def vector(window: dict, links=LINKS) -> List[float]:
    """Flat feature list for a model: per link, STATS in order.

    A link with no readings in the window counts as sitting on its baseline
    (drop 0, std 0). Link health (section 6) is what reports a missing link.
    """
    out: List[float] = []
    for link in links:
        s = window["links"].get(link) or {"n": 0}
        if s["n"] == 0:
            base = window["base"].get(link, 0.0)
            out += [base, 0.0, base, base, 0.0]
        else:
            out += [s["mean"], s["std"], s["min"], s["max"], s["drop_db"] or 0.0]
    return out


def feature_names(links=LINKS) -> List[str]:
    return [f"{link}.{stat}" for link in links for stat in STATS]


class Windower:
    """Turns a stream of bus messages into windows, one per 0.1 s hop.

    Feed messages in recv_t order with push(); it returns the windows that
    closed. Messages without recv_t, or of other types, are ignored.
    """

    def __init__(self, base: Dict[str, float], links=LINKS):
        self.base = dict(base)
        self.links = tuple(links)
        self._rssi: deque = deque()   # (recv_t, link, dbm)
        self._labels: deque = deque()  # (recv_t, label message)
        self._next_end: Optional[int] = None

    def push(self, msg: dict) -> List[dict]:
        t = msg.get("recv_t")
        kind = msg.get("type")
        if t is None or kind not in ("rssi", "label"):
            return []
        t = int(t)
        if self._next_end is None:
            # First window closes one full window after the first message,
            # rounded up to the 100 ms grid.
            self._next_end = -(-(t + WINDOW_MS) // HOP_MS) * HOP_MS
        done = []
        while t >= self._next_end:
            done.append(self._close(self._next_end))
            self._next_end += HOP_MS
        if kind == "rssi":
            self._rssi.append((t, msg["link"], float(msg["dbm"])))
        else:
            self._labels.append((t, msg))
        return done

    def _close(self, end: int) -> dict:
        start = end - WINDOW_MS
        for q in (self._rssi, self._labels):   # keep 2 s: the object rule looks that far back
            while q and q[0][0] < end - STEADY_MS:
                q.popleft()
        per_link: Dict[str, List[float]] = {}
        trail: Dict[str, List[tuple]] = {}
        for t, link, dbm in self._rssi:
            if t < end:
                trail.setdefault(link, []).append((t, dbm))
                if t >= start:
                    per_link.setdefault(link, []).append(dbm)
        labels = [m for t, m in self._labels if start <= t < end]
        return {
            "steady_links": [link for link in self.links
                             if steady_drop(trail.get(link, []), self.base.get(link), end)],
            "persons_2s": max(((m.get("persons_in_frame") or 0) for t, m in self._labels if t < end),
                              default=0),
            "start": start,
            "end": end,
            "base": self.base,
            "links": {link: link_stats(per_link.get(link, []), self.base.get(link))
                      for link in self.links},
            "label": window_label(labels),
        }


def windows(messages: Iterable[dict], base: Dict[str, float], links=LINKS) -> Iterator[dict]:
    """All closed windows of a recorded message stream (sorted by recv_t)."""
    w = Windower(base, links)
    for m in sorted((m for m in messages if "recv_t" in m), key=lambda m: m["recv_t"]):
        yield from w.push(m)
