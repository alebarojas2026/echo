"""Check-in and the no-movement alert (CONTRACTS.md v2, section 6), plus the LED grid.

Pure rules, no sockets: feed it every rssi message and every decision, and it
returns the state's "alert" and "checkin" blocks and the events to send.

Check-in (a rule, not learned): on pi5>unoq:wifi, >= 4 alternating crossings of
+/-1.5 dB around the 1 s rolling median within 2.5 s, with pred.zone unchanged
and no other link's drop changing by > 3 dB. Gate 8 tunes the constants below.

Alert: still_s counts while kind == person, motion == still and the zone is
unchanged. At 10 decisions a second a 10 s stand needs 100 clean decisions in
a row, so the decisions are smoothed first: the zone and the kind are the
majority of the last 10 decisions (6 of 10, else no change), and the timer only resets after 5 "moving"
decisions in a row. One blip doesn't restart the count; real walking does. check_on when still_s >= the zone's still_alert_s (null never
alerts; objects never alert). It clears on a check-in or on reset_alert, and
on nothing else. The timer pauses while pred is null (sensor blind).

LED grid (mcu/, over the Bridge): show_zone(n), alert(on), smile().
show_zone(-1) is "?": pred is null (blind, recalibrating, router away) or the
decision spans 2 or more zones.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from brain import layout
from brain import settings as S

CHECKIN_LINK = "pi5>unoq:wifi"
CROSS_DB = 1.5          # a crossing is this far above or below the rolling median
CROSSINGS = 4           # alternating crossings needed
CROSS_WINDOW_MS = 2500  # ... within this long
MEDIAN_MS = 1000        # the rolling median's length
SMOOTH_N = 3            # at least this many readings are averaged before comparing, so 1 dB noise can't cross
SMOOTH_MS = 200         # ... and all of the last 0.2 s (still 3 readings at 10 or 15 a second, 10 at 50 a second)
OTHER_LINK_DB = 3.0     # no other link may change by more than this
OTHER_BIN_MS = 500      # ... comparing 0.5 s means
# The people rules' numbers (how many decisions make a majority, how many "moving" in a row reset
# the still timer, how long a person must be there to be an intrusion) live in brain/settings.py.
LED_RETRY_S = 30.0      # after a failed LED call, leave the grid alone this long
NODES_JSON = layout.NODES_JSON   # radio/nodes.json


def zone_limits(path=NODES_JSON) -> Dict[int, Optional[float]]:
    """{zone id: still_alert_s or None} from radio/nodes.json."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return {z["id"]: z.get("still_alert_s") for z in doc["zones"]}


class NoLed:
    """Stands in for the LED grid when there is no board."""

    def show_zone(self, n): pass
    def alert(self, on): pass
    def smile(self): pass


class BridgeLed:
    """The LED grid on the microcontroller, called over the Bridge (mcu/ sketch).

    A failed call is logged once and otherwise ignored: the lights must never
    stop the brain. A call can take its whole 1 s timeout, so it never runs on the
    live loop: each call goes to a worker thread, and a call made while the last
    one hasn't come back is dropped (#648). After a failure the grid is left alone
    for LED_RETRY_S. Not yet tried on the board.

    run(fn) starts fn off the loop; the default is a daemon thread. Tests pass
    run=lambda fn: fn() to keep it in line.
    """

    def __init__(self, call=None, clock=time.monotonic, run=None):
        if call is None:
            from arduino.app_utils import Bridge   # the app-bricks wheel; only on the board
            call = Bridge.call
        self._call, self._clock = call, clock
        self._run = run or (lambda fn: threading.Thread(target=fn, name="led", daemon=True).start())
        self._busy = False
        self.dropped = 0
        self._warned = False
        self._quiet_until = float("-inf")

    def _send(self, name, *args):
        if self._clock() < self._quiet_until:
            return
        if self._busy:              # the last call hasn't come back: don't queue behind it
            self.dropped += 1
            return
        self._busy = True

        def work():
            try:
                self._call(name, *args, timeout=1)
            except Exception as e:
                self._quiet_until = self._clock() + LED_RETRY_S
                if not self._warned:
                    self._warned = True
                    logging.getLogger("brain").warning("LED grid call %s failed: %s", name, e)
            finally:
                self._busy = False

        self._run(work)

    def show_zone(self, n): self._send("show_zone", int(n))
    def alert(self, on): self._send("alert", bool(on))
    def smile(self): self._send("smile")


def led_grid():
    """The real LED grid if the Bridge is there, else a stand-in."""
    try:
        return BridgeLed()
    except Exception:
        return NoLed()


class CheckIn:
    """Finds a wave on the check-in link. push() returns True when one completes."""

    def __init__(self, cross_db=CROSS_DB, crossings=CROSSINGS, window_ms=CROSS_WINDOW_MS, other_db=OTHER_LINK_DB):
        """The defaults are the rule the brain runs. brain/tune_checkin.py tries others on a
        recording (other_db None = other links are not looked at)."""
        self.cross_db, self.n_crossings, self.window_ms, self.other_db = cross_db, crossings, window_ms, other_db
        self.wifi: deque = deque()                 # (t, dbm), last MEDIAN_MS
        self.others: Dict[str, deque] = {}         # link -> (t, dbm), last CROSS_WINDOW_MS
        self.other_db_of: Dict[str, float] = {}    # link -> its own limit, where that is over other_db
        self.crossings: deque = deque()            # (t, +1 | -1), alternating
        self.zone_since = 0                        # when pred.zone last changed
        self.quiet_until = 0                       # one wave is one check-in

    def zone_changed(self, t: int) -> None:
        self.zone_since = t
        self.crossings.clear()

    def push(self, t: int, link: str, dbm: float) -> bool:
        if link != CHECKIN_LINK:
            q = self.others.setdefault(link, deque())
            q.append((t, dbm))
            while q and q[0][0] < t - self.window_ms:
                q.popleft()
            return False
        self.wifi.append((t, dbm))
        while self.wifi and self.wifi[0][0] <= t - MEDIAN_MS:
            self.wifi.popleft()
        if len(self.wifi) < 2 * SMOOTH_N:
            return False
        values = [d for _, d in self.wifi]
        # Averaged over time, not over a count: a faster reader must not get more chances to
        # cross on noise alone. At 10 or 15 readings a second this is the last 3, as before.
        last = [d for when, d in self.wifi if when > t - SMOOTH_MS]
        if len(last) < SMOOTH_N:
            last = values[-SMOOTH_N:]
        dev = sum(last) / len(last) - statistics.median(values)
        side = 1 if dev >= self.cross_db else -1 if dev <= -self.cross_db else 0
        if t < self.quiet_until:
            return False
        if side and (not self.crossings or self.crossings[-1][1] != side):
            self.crossings.append((t, side))
        while self.crossings and self.crossings[0][0] < t - self.window_ms:
            self.crossings.popleft()
        if len(self.crossings) < self.n_crossings:
            return False
        first = self.crossings[0][0]
        if self.zone_since > first or not self._others_quiet(first, t):
            return False
        self.crossings.clear()
        self.quiet_until = t + self.window_ms
        return True

    def _others_quiet(self, t0: int, t1: int) -> bool:
        if self.other_db is None:
            return True
        for link, q in self.others.items():
            bins: Dict[int, List[float]] = {}
            for t, d in q:
                if t0 <= t <= t1:
                    bins.setdefault((t - t0) // OTHER_BIN_MS, []).append(d)
            means = [sum(v) / len(v) for v in bins.values() if len(v) >= 2]
            if means and max(means) - min(means) > max(self.other_db, self.other_db_of.get(link, 0.0)):
                return False
        return True


TAMPER_SILENT_MS = S.DEFAULT.tamper_silent_ms   # a node is silent when none of its links has had a reading for this long
TAMPER_CLEAR_MS = S.DEFAULT.tamper_clear_ms     # a node is back when every link of its has gone this long without such a gap


class Tamper:
    """Tamper while armed (section 6; proposed in issue #533): a device unplugged or silenced is noticed.

    A node is silent when every link it sends or receives on has had no reading for 3 s. While
    armed, a node that goes silent raises `tamper` once and is listed until all its links have
    had readings for 2 s without a 3 s gap, or until disarm. Arming with a node already silent
    raises it at once. It does not look at health or pred: it works while the sensor is blind,
    which is the point.

    Ordinary packet loss never gets there: at 10 readings a second and 60% loss, a link going
    3 s without a single reading would take 30 losses in a row, on every link of the node at once.
    The way back uses the same 3 s, so the same loss can't keep a device listed once it is back.

    One step past the contract's wording, so two devices can come back one at a time: a node's
    links to another node that is itself still listed are left out when judging whether it is
    back (it can't be blamed for the other one's silence), as long as one of its links remains.

    The optional hall beacons (nodes.json "hall") count as nodes too, each once it has been heard
    since arming, on the links it has been heard on since then. One that was never switched on, or
    was already off when the space was armed, is not a tamper.
    """

    def __init__(self, links_of: Dict[str, List[str]], silent_ms: int = TAMPER_SILENT_MS,
                 clear_ms: int = TAMPER_CLEAR_MS):
        """links_of: {node: [link ids it sends or receives on]}, from radio/nodes.json."""
        self.links_of = {node: list(links) for node, links in links_of.items() if links}
        self.silent_ms, self.clear_ms = silent_ms, clear_ms
        self.silent: List[str] = []                     # listed nodes, in the order they went silent
        self._back_since: Dict[str, int] = {}
        self._start: Optional[int] = None
        self._core = dict(self.links_of)                # the layout's own nodes
        self._armed_at: Optional[int] = None

    @classmethod
    def from_nodes(cls, doc, **settings) -> "Tamper":
        links_of: Dict[str, List[str]] = {}
        for link in doc["links"]:
            for node in (link["tx"], link["rx"]):
                links_of.setdefault(node, []).append(link["id"])
        return cls(links_of, **settings)

    def update(self, now: int, armed: bool, last_seen: Dict[str, int],
               hall_seen: Optional[Dict[str, Dict[str, int]]] = None) -> List[tuple]:
        """One tick. last_seen: {link: recv_t of its last reading}. hall_seen: the same per hall
        beacon, {node: {link: recv_t}}. Returns (kind, {"node": id}) events."""
        if self._start is None:
            self._start = now
        if not armed:
            events = [("tamper_cleared", {"node": node}) for node in self.silent]
            self.silent, self._back_since = [], {}
            self.links_of, self._armed_at = dict(self._core), None   # hall beacons are counted afresh next time
            return events
        if self._armed_at is None:
            self._armed_at = now
        for node, seen in (hall_seen or {}).items():
            if node in self._core:
                continue
            known = self.links_of.get(node, [])
            heard = [link for link, t in seen.items() if t >= self._armed_at and link not in known]   # since arming
            if known or heard:
                self.links_of[node] = known + heard
                last_seen = {**last_seen, **{link: seen[link] for link in self.links_of[node]}}

        def quiet(link):   # a link never heard counts from when this rule first ran, not from for ever
            return now - last_seen.get(link, self._start) >= self.silent_ms

        events = []
        for node, links in self.links_of.items():
            if node not in self.silent and all(quiet(link) for link in links):
                self.silent.append(node)
                self._back_since.pop(node, None)
                events.append(("tamper", {"node": node}))
        for node in list(self.silent):
            others = [k for k in self.links_of[node]
                      if not any(k in self.links_of[n] for n in self.silent if n != node)]
            if any(quiet(link) for link in others or self.links_of[node]):
                self._back_since.pop(node, None)
            elif now - self._back_since.setdefault(node, now) >= self.clear_ms:
                self.silent.remove(node)
                self._back_since.pop(node, None)
                events.append(("tamper_cleared", {"node": node}))
        return events


class Armed:
    """Armed mode (section 6): the space should be empty, so a person who appears and stays is an intrusion.

    A person appears when present with kind person for the majority of the last 10 decisions
    (6 of them), after that was not so. Still there hold_s later (armed.hold_s in nodes.json,
    3 s): one intrusion. Gone first (not present for the majority of the last 10): they walked
    past, and their zone goes to pop_passed() for a passed_by event instead. One event per
    appearance; a person who stays raises nothing more. Objects raise neither. Decisions with
    pred null (blind, recalibrating) are not decisions: the counts and the wait pause, start
    again when pred is back, and whoever was already in stays "in".
    """

    def __init__(self, settings: Optional[S.Settings] = None, hold_s: float = S.HOLD_S):
        self.settings = settings or S.DEFAULT
        self.hold = round(hold_s * S.DECISIONS_PER_S)   # decisions somebody must stay; 0 = an intrusion at once
        self.on = False
        self._recent: deque = deque(maxlen=self.settings.intrusion_decisions)   # per decision: (a person is present, zone)
        self._inside = False
        self._waited: Optional[int] = None   # decisions since a person appeared, while the wait runs
        self._zone = 0                       # where they appeared
        self._passed: List[int] = []

    def pop_passed(self) -> List[int]:
        """Zones of people who appeared while armed and were gone before the wait was over."""
        out, self._passed = self._passed, []
        return out

    def arm(self, on: bool) -> bool:
        """Returns True when this changed anything. Arming starts from "nobody in": someone
        already standing there is an intrusion within the next 6 decisions."""
        if on == self.on:
            return False
        self.on, self._inside, self._waited = on, False, None
        self._recent.clear()
        return True

    def on_pred(self, pred: Optional[dict]) -> Optional[int]:
        """One decision. Returns the zone of an intrusion to announce, or None."""
        if pred is None:
            self._recent.clear()
            return None
        person = bool(pred.get("present")) and pred.get("kind") == "person"
        self._recent.append((person, pred.get("zone") or 0))
        inside = sum(1 for p, _ in self._recent if p)
        zones = [z for p, z in self._recent if p]
        if not self._inside and inside >= self.settings.intrusion_majority:
            self._inside = True
            if self.on:
                self._zone = max(set(zones), key=zones.count)
                if self.hold <= 0:
                    return self._zone
                self._waited = 0
        elif self._inside and len(self._recent) - inside >= self.settings.intrusion_majority:
            self._inside = False
            if self._waited is not None:         # gone before the wait was over: they walked past
                self._waited = None
                self._passed.append(self._zone)
        elif self._waited is not None:
            self._waited += 1
            if self._waited >= self.hold:
                self._waited = None              # still there: this is the intrusion
                return max(set(zones), key=zones.count) if zones else self._zone
        return None


def _majority(values: list, current, majority: int = S.DEFAULT.smooth_majority):
    """The value that holds a real majority of the decisions (6 of 10 once there are 10),
    otherwise the current one stays."""
    need = min(majority, len(values) // 2 + 1)
    for v in set(values):
        if values.count(v) >= need:
            return v
    return current


LEAN_DB = 4.0          # leaning aside: the crossing lines come back up by this much (or settings.lean_x_quiet x quiet) ...
LEAN_SHARE = 0.5       # ... and by this share of what the person standing there took off them
LEAN_MIN_MS = 300      # for at least this long
LEAN_MAX_MS = 2500     # and no longer: a recovery that stays is the person leaving
STEP_MIN_MS = 300      # on a layout with a presence line: stepping out of the line for at least this long, and back, is the check-in
STOOD_MS = 3000        # "standing there" is the lines' drop smoothed over about this long


class Watch:
    """The check-in and alert rules together, driving the LED grid."""

    def __init__(self, limits: Optional[Dict[int, Optional[float]]] = None, led=None,
                 settings: Optional[S.Settings] = None):
        self.settings = settings or S.DEFAULT
        self.limits = zone_limits() if limits is None else limits
        self.led = led or NoLed()
        self.checkin_rule = CheckIn()
        self.zone = 0            # the zone of the last decision (0 = nobody)
        self.still_ms = 0
        self.alerting = False    # latched: only a check-in or reset_alert clears it
        self.alert_zone: Optional[int] = None
        self.last_t: Optional[int] = None
        self.checkin: Optional[dict] = None
        self._events: List[tuple] = []
        self._person = False
        self._shown: Optional[int] = None   # what the LED grid shows now (-1 = "?")
        self._recent: deque = deque(maxlen=self.settings.smooth_decisions)   # (zone, kind) per decision
        # How often a still timer that had started was put back to zero, and by what. For counting
        # on a recording (brain/replay.py); nothing on the screen reads it.
        self.resets = {"moving": 0, "zone": 0, "gone": 0}
        self._kind = "none"                                    # person | object | none, smoothed
        self._raw_zone = 0                                     # the zone of the last single decision
        self._moving_run = 0
        self._lean_zone = 0
        self._stood: Optional[float] = None    # the crossing lines' drop while the person stands there, smoothed
        self._lean_t: Optional[int] = None     # since when the lines have been back up
        self._lean_last: Optional[int] = None
        # Set by the brain on a layout with a presence line: {"link", "return_ms"}. There the one line's
        # decision is steady by itself, so the alert follows it tick for tick with no smoothing (_on_line):
        # whenever the state's alert is counting or check_on, the pred in the same state is a person,
        # present and still.
        self.line: Optional[dict] = None
        self._still_now = False                # the last decision was a person standing still
        self._gone_t: Optional[int] = None     # since when the decisions have said nobody

    def on_crossing(self, t: int, drop_db: Optional[float], quiet_db: float = 0.0, link: Optional[str] = None) -> None:
        """One decision's drop of the lines that cross the spot (their median drops, averaged), on a
        layout that marks them. This is the check-in there: "lean aside to say you're okay".

        While the still timer is counting or the alert is on, the lines coming back up towards the
        empty level for a moment (by LEAN_DB, or lean_x_quiet x their quiet level, and by half of
        what the person took off them) and then dropping again is a check-in: the alert clears,
        as for a wave. Back up for longer than LEAN_MAX_MS is the person leaving: an alert that was
        on ends, because nobody is there, and no check-in is said."""
        dt, self._lean_last = (0 if self._lean_last is None else max(0, t - self._lean_last)), t
        if drop_db is None:
            return
        if self.line:
            return   # no lean there: a body leaning aside stays in the line. The check-in is stepping out and back (_on_line)
        if self._stood is None or not (self.still_ms > 0 or self.alerting or self._lean_t is not None):
            self._stood, self._lean_t = (drop_db if self._person else None), None
            return
        need = max(LEAN_DB, self.settings.lean_x_quiet * quiet_db)
        up = self._stood - drop_db >= need and drop_db <= self._stood * (1 - LEAN_SHARE)
        if self._lean_t is None:
            if up:
                self._lean_t = t
            else:
                self._stood += (drop_db - self._stood) * min(1.0, dt / STOOD_MS)
            return
        lasted = t - self._lean_t
        if up and lasted > LEAN_MAX_MS:            # they left
            self._stood = self._lean_t = None
            if self.alerting:
                self._clear()
        elif not up and self._stood - drop_db < need / 2:   # back down: they are standing there again
            self._lean_t = None
            if lasted >= LEAN_MIN_MS:
                self.checkin = {"t": t, "link": link or CHECKIN_LINK}
                self._events.append(("checkin", {"zone": self.alert_zone or self.zone or self._lean_zone, "link": link or CHECKIN_LINK}))
                self.led.smile()
                self._clear()

    def _on_line(self, t: int, dt: int, pred: dict) -> None:
        """One decision on a layout with a presence line. The timer counts only while this decision is a
        person standing still. The word moving (already held for motion_hold_s by the brain) puts it back
        to zero and ends an alert that was on. Nobody stops the count at once and shows no alert. While an
        alert is on, the person stepping out of the line (for STEP_MIN_MS or more) and back within
        return_ms is the check-in: the alert ends and the timer starts again. Not back by then is the
        person gone: the alert ends with why "left"."""
        here = bool(pred.get("present")) and pred.get("kind") == "person"
        zone = (pred.get("zone") or 0) if here else 0
        self._kind, self._person = pred.get("kind") or "none", here
        self._still_now = here and pred.get("motion") != "moving"
        away = None if self._gone_t is None else t - self._gone_t
        if here and self.alerting and away is not None and STEP_MIN_MS <= away <= self.line["return_ms"]:
            self.checkin = {"t": t, "link": self.line["link"]}
            self._events.append(("checkin", {"zone": self.alert_zone or zone, "link": self.line["link"]}))
            self.led.smile()
            self._clear("checkin")
        if zone != self.zone:
            self._reset_timer("zone" if zone else "gone")
            self.zone = zone
        elif not here:
            self._reset_timer("gone")
        elif not self._still_now:
            self._reset_timer("moving")
            if self.alerting:
                self._clear("moved")
        else:
            self.still_ms += dt
        self._gone_t = None if here else (t if self._gone_t is None else self._gone_t)
        if self.alerting and self._gone_t is not None and t - self._gone_t > self.line["return_ms"]:
            self._clear("left")
        limit = self.limits.get(zone) if self._still_now else None
        if not self.alerting and limit is not None and self.still_ms >= limit * 1000:
            self.alerting, self.alert_zone = True, zone
            self._events.append(("alert_on", {"zone": zone}))
            self.led.alert(True)

    def on_rssi(self, msg: dict) -> None:
        if self.line:
            return   # one spot: the only check-in is stepping out of the presence line and back (_on_line); a wave on another link is not one
        t = msg["recv_t"]
        if self.checkin_rule.push(t, msg["link"], float(msg["dbm"])) and self._person:
            self.checkin = {"t": t, "link": CHECKIN_LINK}
            self._events.append(("checkin", {"zone": self.zone, "link": CHECKIN_LINK}))
            self.led.smile()
            self._clear()

    def on_pred(self, t: int, pred: Optional[dict]) -> None:
        """One decision. pred None (blind, recalibrating) pauses the timer."""
        dt = 0 if self.last_t is None else max(0, t - self.last_t)
        self.last_t = t
        if pred is None:
            self._show(-1)
            return
        raw_zone = (pred.get("zone") or 0) if pred.get("present") else 0
        raw_person = pred.get("kind") == "person"
        self._show(-1 if len(pred.get("zone_set") or []) >= 2 else raw_zone)
        if raw_zone != self._raw_zone:             # the check-in wants pred.zone itself unchanged
            self._raw_zone = raw_zone
            self.checkin_rule.zone_changed(t)
        if self.line:
            return self._on_line(t, dt, pred)
        self._recent.append((raw_zone, pred.get("kind") or "none"))
        zone = _majority([z for z, _ in self._recent], self.zone, self.settings.smooth_majority)
        self._kind = _majority([k for _, k in self._recent], self._kind, self.settings.smooth_majority)
        self._person = self._kind == "person"
        moving = raw_person and pred.get("motion") == "moving"
        self._moving_run = self._moving_run + 1 if moving else 0
        if zone != self.zone:                      # a change that held for most of the last second
            self._reset_timer("zone" if zone else "gone")
            self._lean_zone = self.zone or zone    # where the person who may be leaning aside was standing
            self.zone = zone
        elif not self._person:
            self._reset_timer("gone")              # nobody
        elif self._moving_run >= self.settings.moving_run:
            self._reset_timer("moving")            # real walking
        else:
            self.still_ms += dt                    # still, give or take a blip
        limit = self.limits.get(zone) if self._person else None
        if not self.alerting and limit is not None and self.still_ms >= limit * 1000:
            self.alerting, self.alert_zone = True, zone
            self._events.append(("alert_on", {"zone": zone}))
            self.led.alert(True)

    def _reset_timer(self, why: str) -> None:
        if self.still_ms > 0:
            self.resets[why] += 1
        self.still_ms = 0

    def _show(self, n: int) -> None:
        if n != self._shown:
            self._shown = n
            self.led.show_zone(n)

    def reset_alert(self) -> None:
        """The reset_alert cmd: clear the alert and start the still timer again."""
        self._clear("reset")

    def reset(self) -> None:
        """The reset cmd (between judges): reset_alert, and forget the last check-in."""
        self._clear("reset")
        self.checkin = None

    def _clear(self, why: Optional[str] = None) -> None:
        """why (only on a layout with a presence line): checkin | moved | left | reset, on the alert_off event."""
        self.still_ms = 0
        if self.alerting:
            self._events.append(("alert_off", {"zone": self.alert_zone, **({"why": why} if why and self.line else {})}))
            self.led.alert(False)
        self.alerting, self.alert_zone = False, None

    def pop_events(self) -> List[tuple]:
        """(kind, info) pairs since the last call, in order."""
        out, self._events = self._events, []
        return out

    def alert_block(self) -> dict:
        """The state's "alert" block."""
        still_s = round(self.still_ms / 1000, 1)
        if self.line and not self._still_now:
            # Nobody there, or somebody moving: nothing is counting and no alert shows, whatever is latched.
            return {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
        if self.alerting:
            return {"state": "check_on", "zone": self.alert_zone, "still_s": still_s,
                    "limit_s": self.limits.get(self.alert_zone)}
        limit = self.limits.get(self.zone) if self._person else None
        if limit is not None and self.still_ms > 0:
            return {"state": "counting", "zone": self.zone, "still_s": still_s, "limit_s": limit}
        # Section 5's empty block: still_s is 0 whenever nothing is counting toward a limit.
        return {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
