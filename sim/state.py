"""Fake brain: turn a scripted path into the screen's `state` and `event` messages.

    python -m sim.state zone_tour            # real time, JSON lines on stdout
    python -m sim.state wave_checkin --fast

For building the room, HUD and game before the real brain exists. Messages follow
CONTRACTS.md section 5 with src "sim". This is a perfect brain: it reads the answer
from the script instead of working it out from radio, so it says nothing about how
well the real one does. Measured numbers (model, board) are 0, meaning not measured.
"""
import argparse
import math
import time
from collections import deque
from statistics import median

from . import fake
from .wire import encoder

STILL_ALERT_S = {1: 60, 2: None, 3: None, 4: 10}   # contract section 3
GRID = {"w": 10, "h": 10, "cell_m": 0.24, "origin_m": [-0.2, -0.2]}
STALE_RATIO, BLIND_AFTER_S, CLEAR_AFTER_S = 0.4, 3.0, 3.0   # section 6, link health
OBJECT_AFTER_S, STATIC_AFTER_S, CHECKIN_AFTER_S = 2.0, 5.0, 1.25
SENTENCES = {   # template narration, one short sentence per event kind
    "enter": "Someone walked into zone {zone}.", "exit": "Zone {zone} is empty again.",
    "zone_change": "Someone moved to zone {zone}.", "checkin": "Someone waved to check in.",
    "alert_on": "No movement in zone {zone} for too long.", "alert_off": "The no-movement alert is cleared.",
    "blind_on": "A radio link went quiet.", "blind_off": "A radio link is back.",
    "object_on": "Something new is sitting near {node}.", "object_off": "The object near {node} is gone.",
    "router_moved": "The router was moved.", "router_home": "The router is back home.",
    "cam_on": "The camera is on.", "cam_off": "The camera is off.", "cam_stalled": "The camera has stalled.",
}


def blob(points) -> list:
    """Grid of dB values: a soft bump at each (x, y, peak_db). index = iy*w + ix."""
    w, h, cell, (ox, oy) = GRID["w"], GRID["h"], GRID["cell_m"], GRID["origin_m"]
    out = []
    for iy in range(h):
        for ix in range(w):
            cx, cy = ox + (ix + 0.5) * cell, oy + (iy + 0.5) * cell
            out.append(round(sum(p * math.exp(-((cx - x) ** 2 + (cy - y) ** 2) / (2 * 0.3 ** 2))
                                 for x, y, p in points), 1))
    return out


class Brain:
    """Feed it the fake feed's events with `see`, ask for a `state(t)`, read `events`."""

    def __init__(self, path: dict, rate: float = 15.0, start_ms: int = 0):
        self.path, self.rate, self.start_ms = path, rate, start_ms
        self.readings = {fake.link_id(*l): deque() for l in fake.LINKS}   # (t, dbm), last 2 s
        self.stale_since, self.ok_since, self.blind = {}, {}, set()
        self.still_s = self.alert_s = 0.0
        self.last_t = self.zone = None
        self.checkin, self.waves_done = None, set()
        self.before, self.events, self.n_events = {}, [], 0
        self.last_dbm = {}
        self.narration = {"text": "Radio Sight is watching the room.", "event_id": "e0",
                          "t": start_ms, "source": "template", "gen_ms": 0}

    def see(self, event: dict) -> None:
        if event["type"] == "rssi":
            self.readings[event["link"]].append((event["t"], event["dbm"]))

    def command(self, msg: dict) -> None:
        """A screen -> brain cmd. Only reset_alert changes anything here."""
        if msg.get("cmd") == "reset_alert":
            self.alert_s = 0.0

    def _ms(self, t: float) -> int:
        return self.start_ms + round(t * 1000)

    def _links(self, t: float) -> list:
        out = []
        for tx, rx, kind in fake.LINKS:
            link, q = fake.link_id(tx, rx, kind), self.readings[fake.link_id(tx, rx, kind)]
            while q and q[0][0] <= t - 2.0:
                q.popleft()
            rate = len(q) / min(2.0, max(t, 1.0 / self.rate))
            if rate < STALE_RATIO * self.rate:
                self.ok_since.pop(link, None)
                if t - self.stale_since.setdefault(link, t) >= BLIND_AFTER_S:
                    self.blind.add(link)
            else:
                self.stale_since.pop(link, None)
                if t - self.ok_since.setdefault(link, t) >= CLEAR_AFTER_S:
                    self.blind.discard(link)
            last = [d for at, d in q if at > t - 1.0]
            base = round(fake.baseline(tx, rx, kind), 1)
            if last:
                self.last_dbm[link] = round(median(last), 1)
            dbm = self.last_dbm.get(link, base)   # a silent link keeps its last level
            out.append({"id": link, "dbm": dbm, "base_dbm": base, "drop_db": round(base - dbm, 1),
                        "rate_hz": round(rate, 1), "expected_hz": self.rate,
                        "status": "blind" if link in self.blind else "stale" if link in self.stale_since else "ok",
                        "why": 0.0})
        return out

    def state(self, t: float) -> dict:
        path = self.path
        dt = 0.0 if self.last_t is None else t - self.last_t
        self.last_t = t
        pos = fake.position(path.get("person") or [], t)
        moving = fake.is_moving(path.get("person") or [], t)
        zone = fake.zone_of(*pos) if pos else 0
        spot = fake.latest(path.get("router"), t, "spot", "S-home")
        cam = fake.latest(path.get("camera"), t, "state", "on")
        nodes = {**fake.NODES, "pi5": fake.ROUTER_SPOTS[spot]}
        things = [o for o in path.get("objects") or []
                  if fake.active(o, t) and t - o.get("t_on", 0.0) >= OBJECT_AFTER_S]

        links = self._links(t)
        blind = sorted(self.blind)
        stale = [l["id"] for l in links if l["status"] != "ok"]
        health = {"status": "blind" if blind else "degraded" if stale else "ok", "blind": blind,
                  "reason": "rate" if stale else None}

        # how much of each link's drop the person explains, for "why"
        share = {fake.link_id(*l): fake.drop(pos, nodes[l[0]], nodes[l[1]], fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M)
                 if pos else 0.0 for l in fake.LINKS}
        total = sum(share.values())
        for l in links:
            l["why"] = round(share[l["id"]] / total, 2) if total > 0.5 else 0.0
        why = [k for k, v in sorted(share.items(), key=lambda kv: -kv[1]) if v > 1.0][:2]

        still = bool(pos) and not moving and zone == self.zone
        self.still_s = self.still_s + dt if still else 0.0
        self.zone = zone
        limit = STILL_ALERT_S.get(zone)
        if not (still and limit):
            self.alert_s = 0.0
        elif not blind:                                  # alert timers pause while blind
            self.alert_s += dt
        for i, w in enumerate(path.get("waves") or []):  # a wave becomes a check-in
            if i not in self.waves_done and t >= w.get("t_on", 0.0) + CHECKIN_AFTER_S and fake.active(w, t):
                self.waves_done.add(i)
                self.checkin = {"t": self._ms(t), "link": w.get("link", "pi5>unoq:wifi")}
                self.alert_s = 0.0
                self._event(t, "checkin", link=self.checkin["link"])

        pred = None
        if not blind and spot == "S-home":
            kind = "person" if pos else "object" if things else "none"
            probs = [0.03] * 5
            probs[zone] = 0.88
            pred = {"present": bool(pos), "kind": kind, "zone": zone, "zone_set": [zone] if pos else [],
                    "probs": probs, "motion": "moving" if moving else "still",
                    "still_s": round(self.still_s, 1), "why": why}
        alert = {"state": "none", "zone": zone, "still_s": 0.0, "limit_s": limit}
        if pred and still and limit:
            alert = {"state": "check_on" if self.alert_s >= limit else "counting", "zone": zone,
                     "still_s": round(self.alert_s, 1), "limit_s": limit}

        objects = [{"xy_m": [o["x"], o["y"]],
                    "near": min(nodes, key=lambda n: math.dist(nodes[n], (o["x"], o["y"]))),
                    "since_s": round(t - o.get("t_on", 0.0), 1),
                    "drop_db": round(max(fake.drop((o["x"], o["y"]), nodes[l[0]], nodes[l[1]],
                                                   o.get("drop_db", 6.0), o.get("width_m", 0.25))
                                         for l in fake.LINKS), 1)} for o in things]
        xray = {**GRID,
                "moving_db": blob([(*pos, 6.0)] if pos and moving else []),
                "static_db": blob([(o["x"], o["y"], o.get("drop_db", 6.0)) for o in things
                                   if t - o.get("t_on", 0.0) >= STATIC_AFTER_S]),
                "n_links": len(links) - len(blind)}

        self._diff(t, {"present": bool(pos), "zone": zone, "alert": alert["state"], "cam": cam, "spot": spot,
                       "blind": set(blind), "objects": {o["near"] for o in objects}, "pred": pred is not None})
        return {"type": "state", "t": t, "cam": cam, "router": spot, "links": links, "health": health,
                "pred": pred, "objects": objects, "xray": xray, "alert": alert, "checkin": self.checkin,
                "advice": None, "narration": self.narration,
                "teacher": {"present": bool(pos), "zone": zone,
                            "motion": ("moving" if moving else "still") if pos else None} if cam == "on" else None,
                # the contract wants numbers here; 0 means "nothing was measured"
                "model": {"trained": True, "ver": "sim", "train_s": 0, "ms_per_decision": 0,
                          "windows": 0, "train_sessions": [], "training": None},
                "board": {"cpu_temp_c": 0, "cpu_mhz": 0, "cpu_pct": 0}}

    def _event(self, t: float, kind: str, **info) -> None:
        self.n_events += 1
        self.events.append({"type": "event", "t": t, "id": f"e{self.n_events}", "kind": kind, "info": info})
        self.narration = {"text": SENTENCES[kind].format(**info), "event_id": f"e{self.n_events}",
                          "t": self._ms(t), "source": "template", "gen_ms": 0}

    def _diff(self, t: float, now: dict) -> None:
        was, self.before = self.before, now
        if not was:
            was = {**now, "present": False, "alert": "none", "blind": set(), "objects": set(), "spot": "S-home"}
        if now["pred"] and was["pred"]:   # presence only means something while there is a prediction
            if now["present"] and not was["present"]:
                self._event(t, "enter", zone=now["zone"])
            elif was["present"] and not now["present"]:
                self._event(t, "exit", zone=was["zone"])
            elif now["present"] and now["zone"] != was["zone"]:
                self._event(t, "zone_change", zone=now["zone"])
        elif not now["pred"]:
            now["present"], now["zone"] = was["present"], was["zone"]
        if (now["alert"] == "check_on") != (was["alert"] == "check_on"):
            self._event(t, "alert_on" if now["alert"] == "check_on" else "alert_off", zone=now["zone"])
        if now["cam"] != was["cam"]:
            self._event(t, "cam_" + now["cam"])
        if now["spot"] != was["spot"]:
            self._event(t, "router_home" if now["spot"] == "S-home" else "router_moved")
        for kind, a, b, key in (("blind_on", now, was, "link"), ("blind_off", was, now, "link"),
                                ("object_on", now, was, "node"), ("object_off", was, now, "node")):
            field = "blind" if key == "link" else "objects"
            for item in sorted(a[field] - b[field]):
                self._event(t, kind, **{key: item})


def run(path: dict, rate: float = 15.0, seed: int = 0, state_hz: float = 10.0, start_ms: int = 0, brain=None):
    """Yield internal `state` and `event` messages for a path, in time order."""
    brain = brain or Brain(path, rate, start_ms)
    tick = 0

    def due(until: float):
        nonlocal tick
        while tick / state_hz <= until:
            state = brain.state(round(tick / state_hz, 3))
            yield from brain.events   # an event goes out just before the state that shows it
            brain.events.clear()
            yield state
            tick += 1

    last = 0.0
    for event in fake.simulate(path, rate=rate, seed=seed):
        if event["t"] > last:
            yield from due(last)
            last = event["t"]
        brain.see(event)
    yield from due(last)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="path name in sim/paths/ or a path JSON file")
    ap.add_argument("--rate", type=float, default=15.0, help="radio readings per link per second")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fast", action="store_true", help="no waiting")
    ap.add_argument("--start-ms", type=int, default=None, help="epoch ms of the first message (default: now)")
    args = ap.parse_args(argv)
    start_ms = int(time.time() * 1000) if args.start_ms is None else args.start_ms
    encode = encoder(start_ms)
    messages = run(fake.load_path(args.path), rate=args.rate, seed=args.seed, start_ms=start_ms)
    try:
        if args.fast:
            for m in messages:
                print(encode(m))
        else:
            fake.pace((m["t"], encode(m)) for m in messages)
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
