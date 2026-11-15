"""One spot: presence from the Wi-Fi line across the gap first (issue #789, measured on the kit).

The layout file names the lines (radio/nodes.json, "presence"):

    "presence": {"line": "pi5>pi5b:wifi", "second": "pi5b>unoq:ble",
                 "on_db": 7, "off_db": 4, "second_hold_s": 5}

- The main line decides. Its drop is the quiet level minus the median of its readings over the
  last second. Somebody is there from a drop of on_db, and stays there until it is back under
  off_db: held while the line stays down, however still they stand.
- The second line is a second opinion. It can keep presence alive for second_hold_s when the
  main line goes silent, and only while its own drop is still off_db or more. It never raises
  presence alone.
- The quiet level starts at the baseline and follows slow drift only while nobody is there.
- With no opinion (no "presence" in the file, no baseline yet, the main line silent and the
  hold over) the answer is None and the classifier's own decision stands.

A layout with no "presence" block gets None for ever: nothing changes on it.
"""
from __future__ import annotations

import statistics
from collections import deque
from typing import Dict, Optional

MEDIAN_MS = 1000        # the drop is a median over this long
FRESH_MS = 1000         # the main line is silent when it has no reading for this long
DRIFT_S = 60.0          # the quiet level moves towards the line this slowly, with nobody there
DEFAULTS = {"on_db": 7.0, "off_db": 4.0, "second_hold_s": 5.0}


class Presence:
    def __init__(self, nodes: Optional[dict]):
        cfg = (nodes or {}).get("presence") or {}
        self.line: Optional[str] = cfg.get("line")
        self.second: Optional[str] = cfg.get("second")
        self.on_db = float(cfg.get("on_db", DEFAULTS["on_db"]))
        self.off_db = float(cfg.get("off_db", DEFAULTS["off_db"]))
        self.second_hold_ms = float(cfg.get("second_hold_s", DEFAULTS["second_hold_s"])) * 1000
        if self.line and not self.off_db < self.on_db:
            raise ValueError("presence.off_db must be under presence.on_db (the line needs a gap to hold in)")
        self._readings: Dict[str, deque] = {k: deque() for k in (self.line, self.second) if k}
        self.quiet: Dict[str, float] = {}      # the quiet level per line (starts at the baseline)
        self.on = False
        self.drop_db: Optional[float] = None   # the main line's drop at the last update, for the log
        self._silent_since: Optional[int] = None
        self._last_t: Optional[int] = None

    @property
    def active(self) -> bool:
        return bool(self.line)

    def set_base(self, base: Dict[str, float]) -> None:
        """A new baseline: the quiet levels start there, and nobody is there (it was taken empty)."""
        self.quiet = {k: float(base[k]) for k in self._readings if k in base}
        self.on, self._silent_since, self._last_t = False, None, None

    def add(self, link: str, t: int, dbm: float) -> None:
        q = self._readings.get(link)
        if q is not None:
            q.append((t, float(dbm)))
            while q and q[0][0] <= t - MEDIAN_MS:
                q.popleft()

    def _drop(self, link: Optional[str], now: int) -> Optional[float]:
        """The line's drop under its quiet level, or None when it is silent or has no baseline."""
        q = self._readings.get(link) if link else None
        if not q or link not in self.quiet:
            return None
        recent = [d for t, d in q if now - FRESH_MS < t <= now]
        return self.quiet[link] - statistics.median(recent) if recent else None

    def update(self, now: int) -> Optional[bool]:
        """True: somebody is on the spot. False: nobody. None: no opinion, the classifier decides."""
        if not self.active or self.line not in self.quiet:
            return None
        dt, self._last_t = (0 if self._last_t is None else max(0, now - self._last_t)), now
        drop = self.drop_db = self._drop(self.line, now)
        if drop is None:                                   # the main line is silent
            if self._silent_since is None:
                self._silent_since = now
            second = self._drop(self.second, now)
            if (self.on and second is not None and second >= self.off_db
                    and now - self._silent_since <= self.second_hold_ms):
                return True                                # kept alive by the second opinion
            self.on = False                                # the hold is over: it never decides alone
            return None
        self._silent_since = None
        if not self.on and drop >= self.on_db:
            self.on = True
        elif self.on and drop < self.off_db:
            self.on = False
        if not self.on and abs(drop) < self.off_db:
            # Slow drift, with nobody there: a drop on its way up to on_db is never absorbed.
            self.quiet[self.line] -= drop * min(1.0, dt / (DRIFT_S * 1000))
        return self.on
