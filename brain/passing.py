"""A walk straight through the presence line (a layout with a presence line only).

Somebody who crosses the line without stopping takes as much off it as somebody who stands in it,
but for well under a second: too short for the 1 s median the presence rule reads, so that rule says
nothing. On the kit's recordings such a crossing is a dip of 14 to 16 dB for 0.28 to 0.84 s, and the
empty line never dips more than about 2 dB. This rule reads the line's own readings (25 a second)
against the same empty level the presence rule uses, and says "somebody walked through" for a
short, deep dip that never became a presence.

It only reads: the readings, the empty level, and whether the presence rule is busy (somebody is
announced as here, or no decision is being shown). It changes nothing the other rules see.

A dip:
- starts with a reading pass_db (9 dB) or more under the empty level;
- is deep enough once such readings have run on for pass_min_s (0.2 s: five in a row at 25 a
  second, counted as readings), where one missing or shallower reading in the run is let through;
- ends with the first reading back within clear_db of the empty level (the presence rule's own
  off_db), no later than pass_max_s (1.5 s) after it began.
Then the rule waits SETTLE_MS, until no 1 s window of the presence rule can still hold the dip. If
the presence rule has announced nobody in all that time, that is one walk-through. If it has
(an enter), the dip was somebody stepping in, and that rule's own events tell it: nothing here.

Nothing is said, and a dip in progress is dropped, while the presence rule is busy and for
HOLD_OFF_MS after: somebody standing there, somebody who just left or stepped aside, the sensor
blind, a baseline being taken, no decision shown. A second dip that begins before the first one's
wait is over replaces it: one crossing, or one person stepping back, is never two events.
"""
from __future__ import annotations

from typing import Optional

PASS_DB = 9.0        # pass_db: a reading this far under the empty level is in a crossing (the empty line dips about 2)
PASS_MIN_S = 0.2     # pass_min_s: such readings have to run on this long (the shortest crossing recorded: 0.28 s)
PASS_MAX_S = 1.5     # pass_max_s: a dip longer than this is not a walk straight through
SETTLE_MS = 1200     # after the dip: the presence rule's 1 s window and two more decisions
HOLD_OFF_MS = 3000   # after the presence rule was busy: no dip counts for this long
SILENT_MS = 200      # a dip with no reading of the line for this long was not seen whole: dropped
PERIOD_MS = 40.0     # the line's readings arrive 25 times a second, unless the baseline measured another rate


class PassThrough:
    def __init__(self, pass_db: float = PASS_DB, min_s: float = PASS_MIN_S, max_s: float = PASS_MAX_S,
                 clear_db: float = 3.0):
        self.pass_db, self.clear_db = float(pass_db), float(clear_db)
        self.min_ms, self.max_ms = float(min_s) * 1000, float(max_s) * 1000
        self._busy_t: Optional[int] = None    # when the presence rule was last busy; None before it ever was
        self._ready = False                   # the presence rule has been seen not busy since the start
        self._last_t: Optional[int] = None    # the line's reading before this one
        self._start: Optional[int] = None     # the dip in progress: its first deep reading
        self._run = 0                         # the run of deep readings in progress: how many ...
        self._run1: Optional[int] = None      # ... and when the latest came
        self._slack = False                   # the run has already let one shallower reading through
        self._deep = False                    # the dip has had a run of pass_min_s
        self._over = False                    # the dip has gone on too long: wait for it to end, say nothing
        self._ended: Optional[int] = None     # a whole dip that waits out SETTLE_MS: when it ended
        self._passed = 0

    def pop(self) -> int:
        """How many walk-throughs there are to announce."""
        out, self._passed = self._passed, 0
        return out

    def _drop(self) -> None:
        self._start = self._run1 = self._ended = None
        self._run = 0
        self._slack = self._deep = self._over = False

    def on_reading(self, t: int, dbm: float, base: Optional[float], busy: bool, period_ms: float = PERIOD_MS) -> None:
        """One reading of the presence line, after the presence rule has had it. base is the line's
        empty level now (None before a baseline); busy is True while somebody is announced as here
        or no decision is being shown."""
        last, self._last_t = self._last_t, t
        if busy or base is None:
            self._busy_t = t
            self._ready = False
            self._drop()
            return
        if not self._ready:
            # The first reading, or the first after the rule was busy: the hold-off runs from here.
            self._ready, self._busy_t = True, (t if self._busy_t is None else self._busy_t)
        down = base - dbm
        if self._busy_t is not None and t - self._busy_t < HOLD_OFF_MS:
            self._drop()
            return
        if self._start is not None and self._ended is None and last is not None and t - last > SILENT_MS:
            self._drop()                      # the line went quiet inside the dip
        if self._ended is not None:
            if down >= self.pass_db:
                self._drop()                  # down again before the wait was over: judged afresh, as one
            elif t - self._ended >= SETTLE_MS:
                self._drop()
                self._passed += 1
                return
            else:
                return
        if self._start is None:
            if down >= self.pass_db:
                self._start, self._run, self._run1 = t, 1, t
            return
        if self._over:
            if down < self.clear_db:
                self._drop()
            return
        if down >= self.pass_db:
            if self._run1 is None or t - self._run1 > 2.75 * period_ms:
                self._run, self._slack = 0, False         # more than one reading missing: a new run
            self._run, self._run1 = self._run + 1, t
            if self._run >= max(2, round(self.min_ms / period_ms)):
                self._deep = True                         # pass_min_s of readings in a row: five at 25 a second
        elif self._run1 is not None:
            if self._slack:
                self._run, self._run1 = 0, None           # a second shallower reading ends the run
            self._slack = True
        if t - self._start > self.max_ms:
            self._over = True
        elif down < self.clear_db:
            if self._deep:
                self._ended = t
            else:
                self._drop()
