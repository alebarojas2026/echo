"""Hall links: is there movement along a long radio path? (optional; contract proposal in issue #358)

Two spare beacons (H and J) sit 10-25 m from the square. A hall link is any link whose tx is one of
them: each receiver in nodes.json that hears one makes a link (h>unoq:ble, j>pi5:ble, ...). The core
links are the ones listed in nodes.json "links". For each hall link this module says "movement on
this path" or not. It never says who, where along the path, or how many.

The physics: a body moving near or across a radio path changes the signal from one reading to the
next, while an empty or still path gives a steady level. So per link:

- spread_db = the std of the link's 0.5 s means over the last 3 s. Means, because the scanners hear
  each advert on one of three channels that fade differently (a quiet link still jitters from
  reading to reading), and because a burst of readings must not count more than a gap.
- stale = fewer than 4 of those six 0.5 s bins hold a reading: the readings stopped, or are too few
  to judge. It clears after 3 s not stale. While stale: activity 0, moving false.
- quiet_db = the link's own quiet level: the 20th percentile of spread_db, sampled once a second
  while not stale, over the last 5 min. It needs 20 samples and is never under 0.5 dB.
- activity = (spread_db / quiet_db - 2) / 4, held to 0-1: 0 up to twice the quiet level, 1 at six
  times. A ratio, not a difference in dB, because a link that jitters more when quiet also swings
  more by chance: its spread wanders up to about three times its quiet level with nobody there.
- moving turns true at activity >= 0.5 (four times quiet) and false after activity has stayed
  < 0.25 (three times) for 1 s.
- busy (wording in issue #584): the quiet level is the link's own, so in a hall that is full all
  the time it climbs, and "four times quiet" then means nothing. empty_quiet_db is the link's
  quiet level measured once with the hall empty (nodes.json, hall.empty_quiet_db: {link id: dB}).
  While the current quiet level is above twice that, the path is busy: moving is false and busy
  is true. A link with no empty_quiet_db has no busy in its row: it is not calibrated, and the
  screen says so.

Nothing is learned and no baseline capture is needed. The thresholds are first values, to be tuned
on the real hardware in the real hall (issue #95).

Hall links never reach the classifier, link health, the x-ray, the alert, the check-in or advice:
brain/core.py hands a hall link's reading to take() and does nothing else with it. Every entry
point here catches its own errors, so a bug in this file can't stop the brain.

    hall = Hall.from_nodes(nodes_doc)     # radio/nodes.json, already parsed; no "hall" section = no hall beacons
    if hall.take(msg): return             # every bus message; True = it was a hall link's reading
    hall.add_to(state, now_ms)            # once per state message; adds "hall" once a hall link was heard
"""
from __future__ import annotations

import logging
import statistics
from collections import deque
from typing import Dict, List, Optional

WINDOW_MS = 3000          # the spread is taken over this long
BIN_MS = 500              # ... as the std of the means of bins this long
MIN_BINS = 4              # fewer bins with a reading than this = stale
RATE_MS = 2000            # rate_hz counts readings over this long
STALE_CLEAR_MS = 3000     # stale clears after this long with enough bins
QUIET_EVERY_MS = 1000     # one spread sample for the quiet level this often
QUIET_KEEP_MS = 300_000   # ... kept this long
QUIET_MIN_SAMPLES = 20    # no quiet level, so no activity, before this many samples
QUIET_PERCENTILE = 0.2
QUIET_FLOOR_DB = 0.5      # readings are whole dBm: a quiet level under this is not real
ZERO_AT, ONE_AT = 2.0, 6.0   # spread / quiet: activity is 0 up to ZERO_AT and 1 from ONE_AT
ON, OFF = 0.5, 0.25       # moving turns on at ON, and off after OFF_HOLD_MS under OFF
OFF_HOLD_MS = 1000
BUSY_AT = 2.0             # busy while the quiet level is above this many times the empty hall's

log = logging.getLogger("brain.hall")


def spread_db(readings, now: int) -> Optional[float]:
    """The std of the 0.5 s means of (recv_t, dbm) readings in the 3 s up to `now`, or None when
    fewer than MIN_BINS of the six bins hold a reading."""
    bins: Dict[int, List[float]] = {}
    for t, dbm in readings:
        age = now - t
        if age < WINDOW_MS:
            bins.setdefault(max(age, 0) // BIN_MS, []).append(dbm)
    if len(bins) < MIN_BINS:
        return None
    return statistics.pstdev(sum(v) / len(v) for v in bins.values())


def quiet_db(samples) -> Optional[float]:
    """The quiet level from (t, spread_db) samples, or None while there are too few."""
    if len(samples) < QUIET_MIN_SAMPLES:
        return None
    ordered = sorted(s for _, s in samples)
    return max(QUIET_FLOOR_DB, ordered[int(QUIET_PERCENTILE * (len(ordered) - 1))])


class _Link:
    def __init__(self, link_id: str, tx: str, rx: str, xy_m, empty_quiet_db: Optional[float] = None):
        self.id, self.tx, self.rx, self.xy_m = link_id, tx, rx, xy_m
        self.empty_quiet_db = empty_quiet_db   # the quiet level with the hall empty; None = not calibrated
        self.heard = False
        self.reset()

    def reset(self) -> None:
        self.readings: deque = deque()   # (recv_t, dbm), the last WINDOW_MS
        self.samples: deque = deque()    # (t, spread_db), one a second, the last QUIET_KEEP_MS
        self.stale = True
        self.enough_since: Optional[int] = None
        self.moving = False
        self.under_since: Optional[int] = None
        self.last_now: Optional[int] = None

    def add(self, t: int, dbm: float) -> None:
        self.heard = True
        self.readings.append((t, dbm))

    def row(self, now: int) -> dict:
        if self.last_now is not None and now < self.last_now - WINDOW_MS:
            self.reset()                 # the clock went back (a recording played again): start over
        self.last_now = now
        r = self.readings
        while r and now - r[0][0] >= WINDOW_MS:
            r.popleft()
        spread = spread_db(r, now)
        if spread is None:
            self.stale, self.enough_since = True, None
        else:
            if self.enough_since is None:
                self.enough_since = now
            if now - self.enough_since >= STALE_CLEAR_MS:
                self.stale = False
        activity, busy = 0.0, False
        if self.stale:
            self.moving, self.under_since = False, None
        else:
            s = self.samples
            if not s or now - s[-1][0] >= QUIET_EVERY_MS:
                s.append((now, spread))
            while s and now - s[0][0] >= QUIET_KEEP_MS:
                s.popleft()
            quiet = quiet_db(s)
            if quiet is not None:
                activity = min(1.0, max(0.0, (spread / quiet - ZERO_AT) / (ONE_AT - ZERO_AT)))
            busy = self.empty_quiet_db is not None and quiet is not None \
                and quiet > BUSY_AT * self.empty_quiet_db
            if busy:
                self.moving, self.under_since = False, None   # a full hall: "movement" would always be true
            elif activity >= ON:
                self.moving, self.under_since = True, None
            elif activity >= OFF:
                self.under_since = None
            elif self.moving:
                if self.under_since is None:
                    self.under_since = now
                if now - self.under_since >= OFF_HOLD_MS:
                    self.moving, self.under_since = False, None
        rate = sum(1 for t, _ in r if now - t < RATE_MS) / (RATE_MS / 1000)
        out = {"id": self.id, "tx": self.tx, "rx": self.rx, "xy_m": self.xy_m,
               "activity": round(activity, 2), "moving": self.moving,
               "rate_hz": round(rate, 1), "stale": self.stale}
        if self.empty_quiet_db is not None:
            out["busy"] = busy            # absent = this link has no empty-hall level yet
        return out


class Hall:
    def __init__(self, beacons=None, receivers=(), empty_quiet_db=None):
        """beacons: {hall beacon node: [x, y] in metres, or None while it hasn't been measured}.
        receivers: the receiver nodes, in nodes.json order. A link is listed once it has a reading,
        ordered by receiver, then by beacon.
        empty_quiet_db: {hall link id: its quiet level with the hall empty, dB}, for busy."""
        self._beacons = dict(beacons or {})
        empty = dict(empty_quiet_db or {})
        self._links: Dict[str, _Link] = {
            f"{tx}>{rx}:ble": _Link(f"{tx}>{rx}:ble", tx, rx, xy, empty.get(f"{tx}>{rx}:ble"))
            for rx in receivers for tx, xy in self._beacons.items()}
        self._told = False

    @classmethod
    def from_nodes(cls, doc) -> "Hall":
        """Build from radio/nodes.json, already parsed: the beacons of its "hall" section, and every
        node with the receiver role. No "hall" section, or one that can't be read, gives a Hall
        with no beacons: it takes nothing and adds nothing."""
        try:
            hall = (doc or {}).get("hall")
            if not hall:
                return cls()
            beacons = {}
            for b in hall["beacons"]:
                xyz = b.get("xyz_m")
                beacons[str(b["node"])] = None if xyz is None else [float(xyz[0]), float(xyz[1])]
            core = {str(n["id"]) for n in doc["nodes"]}
            if core & set(beacons):
                raise ValueError(f"hall beacons {sorted(core & set(beacons))} are also nodes of the square")
            receivers = [str(n["id"]) for n in doc["nodes"] if "receiver" in n.get("roles", [])]
            empty = {}
            for link, db in (hall.get("empty_quiet_db") or {}).items():
                if isinstance(db, (int, float)) and not isinstance(db, bool) and db > 0:
                    empty[str(link)] = max(QUIET_FLOOR_DB, float(db))   # the same floor as the live quiet level
                else:
                    log.warning("hall.empty_quiet_db for %s is not a level in dB (%r): that link stays not calibrated", link, db)
            return cls(beacons, receivers, empty)
        except Exception as e:
            log.warning("the hall section of nodes.json can't be read (%r): no hall links", e)
            return cls()

    def take(self, msg) -> bool:
        """True when msg is an rssi reading whose tx is a hall beacon. The caller then does nothing
        else with it, so hall readings never reach the core links' rules. A reading heard by
        something that isn't a receiver in nodes.json is taken too, and dropped. Never raises."""
        try:
            if not self._beacons or msg.get("type") != "rssi":
                return False
            name = msg.get("link")
            if not isinstance(name, str) or name.split(">", 1)[0] not in self._beacons:
                return False
        except Exception:
            return False          # not something we can name as ours: the caller treats it as before
        try:
            link = self._links.get(name)
            if link is not None:
                link.add(int(msg["recv_t"]), float(msg["dbm"]))
        except Exception as e:    # a reading with no recv_t or no number: dropped
            self._tell(e)
        return True

    def rows(self, now: int) -> list:
        """One row per hall link that has ever had a reading, by receiver in nodes.json order and
        then by beacon. Never raises."""
        out = []
        for link in self._links.values():
            if not link.heard:
                continue
            try:
                out.append(link.row(int(now)))
            except Exception as e:
                self._tell(e)
                try:
                    link.reset()
                except Exception:
                    pass
        return out

    def add_to(self, state: dict, now: int) -> dict:
        """Put "hall" into a state message once a hall link has been heard, and hand the state back.
        With no hall beacon heard the state is left exactly as it was."""
        rows = self.rows(now)
        if rows:
            state["hall"] = rows
        return state

    def _tell(self, e: Exception) -> None:
        if not self._told:        # once: this may happen ten times a second
            self._told = True
            log.warning("hall links: %r (the core links are not affected)", e)
