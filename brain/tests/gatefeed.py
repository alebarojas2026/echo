"""A made-up feed shaped like the gate layout on the real kit, for the brain's own tests.

What the kit showed (issue #95): the Bluetooth lines between Pi B and the board / Pi A arrive
at about 6 readings a second (one of them at about 2), wobble 2 to 5 dB with nobody there, and
drop 10 to 14 dB while a person stands between. The two lines over the desk and both Wi-Fi
lines don't react to a person. Readings are whole dBm and come at uneven times.

This is a stand-in, not a measurement: it shows the rules hold at those rates and that noise,
and says nothing about how well the real desk works.
"""
import json
import math
import random
from pathlib import Path

# This folder's own copy of the gate layout, like square_nodes.json: the tests don't move when the desk is measured.
GATE = json.loads((Path(__file__).resolve().parent / "gate_nodes.json").read_text(encoding="utf-8"))
LINKS = [link["id"] for link in GATE["links"]]
# readings a second, level in dBm, and the drop with a person on the spot (0: the line doesn't cross it)
RATE = {"pi5>unoq:wifi": 10.0, "pi5>unoq:ble": 6.0, "pi5b>unoq:ble": 6.0, "pi5>pi5b:wifi": 25.0,
        "pi5>pi5b:ble": 6.0, "pi5b>pi5:ble": 2.0}
LEVEL = {"pi5>unoq:wifi": -38, "pi5>unoq:ble": -42, "pi5b>unoq:ble": -58, "pi5>pi5b:wifi": -47,
         "pi5>pi5b:ble": -61, "pi5b>pi5:ble": -63}
# The Wi-Fi line from Pi A to Pi B is the one that decides: 15 to 21 dB with a person, 25 readings a second.
DROP = {"pi5>pi5b:wifi": 18.0, "pi5b>unoq:ble": 8.0, "pi5>pi5b:ble": 8.0, "pi5b>pi5:ble": 5.0}
RAMP_S = 0.3   # stepping in or out takes about this long
THING_DB = 5.0   # what a thing left standing in the Wi-Fi line takes off it: steady, with no body in it


class Feed:
    """Readings, camera labels and cam messages for a plan of (seconds, who) steps, one after another.

    who: "nobody", "still" (standing), "shift" (standing, shifting their weight), "moving"
    (stepping about on the spot), "lean" (leaning aside, nearly out of the lines) or "thing" (nobody there,
    and something left standing in the Wi-Fi line from Pi A to Pi B: THING_DB off that line, as steady as the
    empty line). wobble_db is the spread (one standard deviation) of a Bluetooth
    line with nobody there: 1.2 gives a 2 to 5 dB wobble peak to peak over a few seconds, half of
    it slow. camera=False sends no labels and cam off (the camera is unplugged).
    """

    def __init__(self, t0, seed=0, wobble_db=1.2, rate=RATE, drop=DROP, drift_db_per_min=0.0):
        self.t, self.rng, self.wobble, self.rate, self.drop = float(t0), random.Random(seed), wobble_db, dict(rate), dict(drop)
        self.slow = {link: 0.0 for link in LINKS}      # the slow half of each line's wobble
        self.drift, self.t0 = drift_db_per_min, float(t0)   # the empty level of the Bluetooth lines to Pi B sinks this fast
        self.depth = 0.0                               # 0 nobody .. 1 fully in the lines
        self.thing, self.thing_db = 0.0, THING_DB      # 0 nothing .. 1 the thing stands in the Wi-Fi line
        self.sway = {link: 0.0 for link in [None] + LINKS}   # the body's own movement: one part shared, one per line
        self.next = {link: self.t + self.rng.random() / self.rate[link] for link in LINKS}

    def play(self, plan, camera=True, send=lambda msg: None):
        out = []
        for seconds, who in plan:
            end = self.t + seconds * 1000
            while self.t < end:
                for msg in self._step(who, camera):
                    out.append(msg)
                    send(msg)
        return out

    def _step(self, who, camera, dt_ms=20):
        t, rng, out = self.t, self.rng, []
        want = {"nobody": 0.0, "lean": 0.1, "thing": 0.0}.get(who, 1.0)   # leaning aside: nearly out of the lines
        self.depth += max(-dt_ms / 1000 / RAMP_S, min(dt_ms / 1000 / RAMP_S, want - self.depth))
        self.thing += max(-dt_ms / 1000 / RAMP_S, min(dt_ms / 1000 / RAMP_S, (who == "thing") - self.thing))
        # a body that shifts or steps changes how much of each line it covers, a couple of times a second
        size = {"shift": 1.5, "moving": 3.0}.get(who, 0.0)
        for key in self.sway:
            sway = self.sway[key] - self.sway[key] * dt_ms / 400 + rng.gauss(0, 1) * size * 0.7 * math.sqrt(dt_ms / 200)
            self.sway[key] = max(-1.4 * size, min(1.4 * size, sway))   # never so far that the body leaves the lines
        tick = int(t)
        for link in LINKS:
            ble = link.endswith(":ble")
            spread = self.wobble if ble else 0.4
            self.slow[link] += -self.slow[link] * dt_ms / 3000 + rng.gauss(0, 1) * spread * 0.7 * math.sqrt(2 * dt_ms / 3000)
            while self.next[link] <= t:
                drop = self.drop.get(link, 0.0) * self.depth
                if drop:
                    drop += (self.sway[None] + self.sway[link]) * self.depth
                if link == "pi5>pi5b:wifi":
                    drop += self.thing_db * self.thing
                if link in DROP and ble:
                    drop += self.drift * (t - self.t0) / 60000
                dbm = LEVEL[link] - drop + self.slow[link] + rng.gauss(0, spread * 0.7)
                out.append({"v": 2, "type": "rssi", "t": tick, "recv_t": tick, "seq": 0, "src": "sim", "link": link,
                            "kind": link.split(":")[1], "tx": link.split(">")[0], "rx": link.split(">")[1].split(":")[0],
                            "dbm": round(dbm)})
                self.next[link] += rng.expovariate(1.0) * 0.5e3 / self.rate[link] + 0.5e3 / self.rate[link]
        if tick % 140 < dt_ms:   # about 7 labels a second
            if camera:
                here = self.depth > 0.5
                out.append({"v": 2, "type": "label", "t": tick, "recv_t": tick, "seq": 0, "src": "sim", "frame": tick // 140,
                            "mode": "person", "persons_in_frame": int(here), "present": here, "zone": int(here),
                            "foot_m": None, "motion": ("moving" if who == "moving" else "still") if here else None,
                            "conf": 0.9, "clipped": 0.2 < self.depth < 0.8})
        if tick % 1000 < dt_ms:
            out.append({"v": 2, "type": "cam", "t": tick, "recv_t": tick, "seq": 0, "src": "sim",
                        "state": "on" if camera else "off", "fps": 7.0 if camera else 0.0})
        self.t += dt_ms
        return out
