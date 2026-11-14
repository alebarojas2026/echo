"""Check-in and the no-movement alert (CONTRACTS.md v2, section 6), plus the LED grid.

Pure rules, no sockets: feed it every rssi message and every decision, and it
returns the state's "alert" and "checkin" blocks and the events to send.

Check-in (a rule, not learned): on pi5>unoq:wifi, >= 4 alternating crossings of
+/-1.5 dB around the 1 s rolling median within 2.5 s, with pred.zone unchanged
and no other link's drop changing by > 3 dB. Gate 8 tunes the constants below.

Alert: still_s counts while kind == person, motion == still and the zone is
unchanged. check_on when still_s >= the zone's still_alert_s (null never
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
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

CHECKIN_LINK = "pi5>unoq:wifi"
CROSS_DB = 1.5          # a crossing is this far above or below the rolling median
CROSSINGS = 4           # alternating crossings needed
CROSS_WINDOW_MS = 2500  # ... within this long
MEDIAN_MS = 1000        # the rolling median's length
SMOOTH_N = 3            # readings averaged before comparing, so 1 dB noise can't cross
OTHER_LINK_DB = 3.0     # no other link may change by more than this
OTHER_BIN_MS = 500      # ... comparing 0.5 s means
NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"


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
    stop the brain. Not yet tried on the board.
    """

    def __init__(self):
        from arduino.app_utils import Bridge   # the app-bricks wheel; only on the board
        self._call = Bridge.call
        self._warned = False

    def _send(self, name, *args):
        try:
            self._call(name, *args, timeout=1)
        except Exception as e:
            if not self._warned:
                self._warned = True
                logging.getLogger("brain").warning("LED grid call %s failed: %s", name, e)

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

    def __init__(self):
        self.wifi: deque = deque()                 # (t, dbm), last MEDIAN_MS
        self.others: Dict[str, deque] = {}         # link -> (t, dbm), last CROSS_WINDOW_MS
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
            while q and q[0][0] < t - CROSS_WINDOW_MS:
                q.popleft()
            return False
        self.wifi.append((t, dbm))
        while self.wifi and self.wifi[0][0] <= t - MEDIAN_MS:
            self.wifi.popleft()
        if len(self.wifi) < 2 * SMOOTH_N:
            return False
        values = [d for _, d in self.wifi]
        dev = sum(values[-SMOOTH_N:]) / SMOOTH_N - statistics.median(values)
        side = 1 if dev >= CROSS_DB else -1 if dev <= -CROSS_DB else 0
        if t < self.quiet_until:
            return False
        if side and (not self.crossings or self.crossings[-1][1] != side):
            self.crossings.append((t, side))
        while self.crossings and self.crossings[0][0] < t - CROSS_WINDOW_MS:
            self.crossings.popleft()
        if len(self.crossings) < CROSSINGS:
            return False
        first = self.crossings[0][0]
        if self.zone_since > first or not self._others_quiet(first, t):
            return False
        self.crossings.clear()
        self.quiet_until = t + CROSS_WINDOW_MS
        return True

    def _others_quiet(self, t0: int, t1: int) -> bool:
        for q in self.others.values():
            bins: Dict[int, List[float]] = {}
            for t, d in q:
                if t0 <= t <= t1:
                    bins.setdefault((t - t0) // OTHER_BIN_MS, []).append(d)
            means = [sum(v) / len(v) for v in bins.values() if len(v) >= 2]
            if means and max(means) - min(means) > OTHER_LINK_DB:
                return False
        return True


class Watch:
    """The check-in and alert rules together, driving the LED grid."""

    def __init__(self, limits: Optional[Dict[int, Optional[float]]] = None, led=None):
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

    def on_rssi(self, msg: dict) -> None:
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
        zone = (pred.get("zone") or 0) if pred.get("present") else 0
        self._person = pred.get("kind") == "person"
        self._show(-1 if len(pred.get("zone_set") or []) >= 2 else zone)
        if zone != self.zone:
            self.zone = zone
            self.still_ms = 0
            self.checkin_rule.zone_changed(t)
        elif self._person and pred.get("motion") == "still":
            self.still_ms += dt
        else:
            self.still_ms = 0
        limit = self.limits.get(zone) if self._person else None
        if not self.alerting and limit is not None and self.still_ms >= limit * 1000:
            self.alerting, self.alert_zone = True, zone
            self._events.append(("alert_on", {"zone": zone}))
            self.led.alert(True)

    def _show(self, n: int) -> None:
        if n != self._shown:
            self._shown = n
            self.led.show_zone(n)

    def reset_alert(self) -> None:
        """The reset_alert cmd: clear the alert and start the still timer again."""
        self._clear()

    def reset(self) -> None:
        """The reset cmd (between judges): reset_alert, and forget the last check-in."""
        self._clear()
        self.checkin = None

    def _clear(self) -> None:
        self.still_ms = 0
        if self.alerting:
            self._events.append(("alert_off", {"zone": self.alert_zone}))
            self.led.alert(False)
        self.alerting, self.alert_zone = False, None

    def pop_events(self) -> List[tuple]:
        """(kind, info) pairs since the last call, in order."""
        out, self._events = self._events, []
        return out

    def alert_block(self) -> dict:
        """The state's "alert" block."""
        still_s = round(self.still_ms / 1000, 1)
        if self.alerting:
            return {"state": "check_on", "zone": self.alert_zone, "still_s": still_s,
                    "limit_s": self.limits.get(self.alert_zone)}
        limit = self.limits.get(self.zone) if self._person else None
        if limit is not None and self.still_ms > 0:
            return {"state": "counting", "zone": self.zone, "still_s": still_s, "limit_s": limit}
        # Section 5's empty block: still_s is 0 whenever nothing is counting toward a limit.
        return {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
