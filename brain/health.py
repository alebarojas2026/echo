"""Link health and SENSOR BLIND (CONTRACTS.md sections 5 and 6).

Pure numpy, no I/O. brain/main.py feeds it every reading and calls update()
once per state message. It returns the section 5 "health" dict, per-link
fields for "links", and blind_on / blind_off events.

Rules (section 6):
- A link is stale when its rate over the last 2 s is < 0.4 x expected_hz.
- It is blind when stale for >= 3 s, or when pred.kind == "none" and
  |median - base| > 6 dB for >= 3 s. The median is over the last 1 s. The
  jump rule is off while the router is off S-home or a baseline is running.
- health is blind when any classifier link is blind. A blind link clears
  after 3 s ok.
- A link whose baseline counted under 4 readings a second is never blind by rate: it shows
  stale while it reads under 0.4 x expected_hz, and that is all. (At 1.6 a second a link
  has fewer than two readings in 2 s about one time in six with nothing wrong.)
status is "degraded" when some link is stale or blind but health isn't blind.
"""
from collections import deque

import numpy as np

from brain.layout import LINKS   # radio/nodes.json's links, in file order

RATE_WINDOW_S = 2.0
STALE_FRAC = 0.4
MEDIAN_WINDOW_S = 1.0
JUMP_DB = 6.0
BLIND_AFTER_S = 3.0
BLIND_RATE_MIN_HZ = 4.0   # a link slower than this at the baseline is never blind by rate
CLEAR_AFTER_S = 3.0
EPS_S = 1e-6           # float slack on the timers
STEADY_S = 5.0         # a steady drop is judged over up to this long (the x-ray's static test)
STEADY_MIN_S = 2.0     # ... and needs at least this much of it
STEADY_STD_DB = 0.8    # std of the 0.5 s means under this = steady
STEADY_BIN_S = 0.5


class _Link:
    def __init__(self, link_id, expected_hz=None, base_dbm=None):
        self.id = link_id
        self.expected_hz = expected_hz
        self.base_dbm = base_dbm
        self.readings = deque()      # (t_s, dbm), last RATE_WINDOW_S only
        self.trail = deque()         # (t_s, dbm), last STEADY_S, for the steady-drop test
        self.blind = False
        self.reason = None           # "rate" | "jump" while blind
        self.stale_since = None
        self.jump_since = None
        self.ok_since = None

    def judge(self, now, judge_rate, nobody):
        """Update stale / blind for this tick. Returns the per-link dict."""
        r = self.readings
        while r and r[0][0] <= now - RATE_WINDOW_S:
            r.popleft()
        rate = len(r) / RATE_WINDOW_S
        recent = [d for t, d in r if t > now - MEDIAN_WINDOW_S]
        dbm = float(np.median(recent)) if recent else None

        stale = (judge_rate and self.expected_hz is not None
                 and rate < STALE_FRAC * self.expected_hz)
        off_base = (nobody and dbm is not None and self.base_dbm is not None
                    and abs(dbm - self.base_dbm) > JUMP_DB)
        self.stale_since = (self.stale_since if self.stale_since is not None else now) if stale else None
        self.jump_since = (self.jump_since if self.jump_since is not None else now) if off_base else None
        # A drop that holds steady is an object in the way (the tray), not a broken link.
        jump = off_base and not (dbm < self.base_dbm and self._steady_since(self.jump_since, now))
        ok = not stale and not jump
        self.ok_since = (self.ok_since if self.ok_since is not None else now) if ok else None

        if not self.blind:
            if (self.stale_since is not None and now - self.stale_since >= BLIND_AFTER_S - EPS_S
                    and self.expected_hz >= BLIND_RATE_MIN_HZ):
                self.blind, self.reason = True, "rate"
            elif jump and now - self.jump_since >= BLIND_AFTER_S - EPS_S:
                self.blind, self.reason = True, "jump"
        elif self.ok_since is not None and now - self.ok_since >= CLEAR_AFTER_S - EPS_S:
            self.blind, self.reason = False, None

        status = "blind" if self.blind else "stale" if stale else "ok"
        drop = None if dbm is None or self.base_dbm is None else self.base_dbm - dbm
        return {"id": self.id,
                "dbm": None if dbm is None else round(dbm, 1),
                "base_dbm": None if self.base_dbm is None else round(self.base_dbm, 1),
                "drop_db": None if drop is None else round(drop, 1),
                "rate_hz": round(rate, 1),
                "expected_hz": self.expected_hz,
                "status": status,
                "_stale": stale}


    def _steady_since(self, since, now):
        """True when the readings since `since` (at most the last STEADY_S) hold steady:
        they span most of that time and the std of their 0.5 s means is under STEADY_STD_DB."""
        while self.trail and self.trail[0][0] <= now - STEADY_S:
            self.trail.popleft()
        t0 = max(since, now - STEADY_S)
        span = now - t0
        pts = [(t, d) for t, d in self.trail if t >= t0]
        if span < STEADY_MIN_S - EPS_S or len(pts) < 2 or pts[-1][0] - pts[0][0] < 0.8 * span:
            return False
        bins = {}
        for t, d in pts:
            bins.setdefault(int((t - t0) // STEADY_BIN_S), []).append(d)
        means = [sum(v) / len(v) for v in bins.values()]
        return len(means) >= 2 and float(np.std(means)) < STEADY_STD_DB


class Health:
    """Readings in, section 5 "health", per-link status and blind events out.

        hm = Health.from_nodes(nodes_doc)    # expected_hz from radio/nodes.json
        hm.set_base({link: base_dbm})        # after baseline_done
        hm.add(link, recv_t_ms, dbm)         # every rssi message
        out = hm.update(now_ms, kind, router_home, baseline_running)   # once per state message
        state["health"] = out["health"]      # pred = None while hm.blind
    """

    def __init__(self, links=LINKS, expected_hz=None, base_dbm=None, classifier_links=None):
        expected_hz = expected_hz or {}
        base_dbm = base_dbm or {}
        self.links = {k: _Link(k, expected_hz.get(k), base_dbm.get(k)) for k in links}
        self.classifier_links = list(classifier_links or links)
        self.blind = False
        self._blind_links = []
        self._start = None

    @classmethod
    def from_nodes(cls, doc, base_dbm=None, classifier_links=None):
        """Build from radio/nodes.json, already parsed (links with expected_hz)."""
        links = [link["id"] for link in doc["links"]]
        hz = {link["id"]: link.get("expected_hz") for link in doc["links"]}
        return cls(links, hz, base_dbm, classifier_links)

    def set_base(self, base_dbm):
        """{link: base_dbm}, after a baseline."""
        for k, v in base_dbm.items():
            if k in self.links:
                self.links[k].base_dbm = None if v is None else float(v)

    def set_expected(self, expected_hz):
        """{link: expected_hz}, after a baseline capture measures it."""
        for k, v in expected_hz.items():
            if k in self.links:
                self.links[k].expected_hz = None if v is None else float(v)

    def add(self, link, t_ms, dbm):
        lk = self.links.get(link)
        if lk is not None:
            lk.readings.append((t_ms / 1000.0, float(dbm)))
            lk.trail.append((t_ms / 1000.0, float(dbm)))
            while lk.trail[0][0] <= t_ms / 1000.0 - STEADY_S:   # never more than the last 5 s
                lk.trail.popleft()

    def update(self, now_ms, kind=None, router_home=True, baseline_running=False, rates_known=True):
        """One tick. kind = the classifier's pred.kind ("person" | "object" | "none"),
        even while pred is withheld; None when there is no prediction (untrained).
        The jump rule only runs when kind == "none", router_home is True (the
        router sits on S-home) and baseline_running is False (no baseline or
        recalibrating capture).

        rates_known False = the expected rates are being measured again (a baseline asked for
        by hand: maybe new beacons, maybe a new room), so no link is judged stale against the
        old ones meanwhile.

        Returns {"health": {...}, "links": [...], "events": [...]}.
        """
        now = now_ms / 1000.0
        if self._start is None:
            self._start = now
        judge_rate = rates_known and now - self._start >= RATE_WINDOW_S - EPS_S   # a full window first
        judge_jump = kind == "none" and router_home and not baseline_running
        rows = [lk.judge(now, judge_rate, judge_jump) for lk in self.links.values()]

        all_blind = [r["id"] for r in rows if r["status"] == "blind"]
        bad_cls = [k for k in self.classifier_links if k in all_blind]
        # health.blind names only links that can blind the sensor. A link outside
        # classifier_links (heard over the hotspot) shows blind in its own row and makes
        # health degraded, nothing more.
        blind = bad_cls
        if bad_cls:
            status, reason = "blind", self.links[bad_cls[0]].reason
        elif any(r["status"] != "ok" for r in rows):
            status = "degraded"
            reason = "rate" if any(r["_stale"] for r in rows) else self.links[all_blind[0]].reason
        else:
            status, reason = "ok", None
        for r in rows:
            del r["_stale"]

        events = []
        if bad_cls and not self.blind:
            events.append({"kind": "blind_on", "info": {"link": bad_cls[0], "links": bad_cls,
                                                        "reason": reason}})
        elif self.blind and not bad_cls:
            events.append({"kind": "blind_off", "info": {"link": self._blind_links[0],
                                                         "links": self._blind_links}})
        self.blind = bool(bad_cls)
        if bad_cls:
            self._blind_links = bad_cls
        return {"health": {"status": status, "blind": blind, "reason": reason},
                "links": rows, "events": events}
