"""Fake brain: turn a scripted path into the screen's `state` and `event` messages.

    python -m sim.state demo                 # real time, JSON lines on stdout
    python -m sim.state wave_checkin --fast

For building the room, HUD and game before the real brain exists. Messages follow
CONTRACTS.md section 5 with src "sim". This is a perfect brain: it reads the answer
from the script instead of working it out from radio, so it says nothing about how
well the real one does. Anything a real brain would measure (model, board) is null.

It starts the way a real one does: no baseline and no model. To keep paths short it
finishes its "baseline" 1 s in and its "training" 2 s in, sending both events.
"""
import argparse
import math
import time
from collections import Counter, deque
from statistics import mean, median, pstdev

from . import fake
from .layout import LAYOUT
from .wire import encoder
from narrator.recap import template as recap_template

STILL_ALERT_S = dict(LAYOUT.zones)   # zone -> still_alert_s, from radio/nodes.json (section 3)
GRID = LAYOUT.grid                   # section 6: the layout plus 0.2 m on each side
BASELINE_AT_S, TRAINED_AT_S = 1.0, 2.0
STALE_RATIO, BLIND_AFTER_S, CLEAR_AFTER_S = 0.4, 3.0, 3.0   # section 6, link health
OBJECT_AFTER_S, STATIC_AFTER_S, CHECKIN_AFTER_S = 2.0, 5.0, 1.25
ADVICE_WITHIN_M, RESULT_WAIT_S, MEDIAN_S = 0.5, 2.0, 3.0    # section 6, advice
ADVICE_DROP_DB = 3.0      # section 6: advice only while pi5>unoq:wifi drops at least this much now
JUMP_DB, STEADY_DB = 6.0, 0.8        # section 6: the jump rule, and what counts as a steady drop
MOVING_RUN, RECENT = 5, 10           # section 6: the still timer is judged on smoothed decisions
OBJECT_GONE_S = 1.0                  # section 6: a removed object's link comes down after about 1 s
NEAR_M = 0.5   # section 5: near is the closest node within this distance, else null
WIFI = "pi5>unoq:wifi"
IDLE_ALERT = {"state": "none", "zone": None, "still_s": 0, "limit_s": None}
SENTENCES = {   # template narration, one short sentence per event kind
    "baseline_done": "The empty-room baseline is done.", "trained": "The radio model is trained.",
    "enter": "Someone walked into zone {zone}.", "exit": "Zone {zone} is empty again.",
    "zone_change": "Someone moved to zone {zone}.", "checkin": "Someone waved to check in.",
    "alert_on": "No movement in zone {zone} for too long.", "alert_off": "The no-movement alert is cleared.",
    "blind_on": "A radio link went quiet.", "blind_off": "A radio link is back.",
    "object_on": "Something new is sitting near {node}.", "object_off": "The object near {node} is gone.",
    "advice": "Something is blocking the router's link, so try moving the router.",
    "advice_result": "The router's link went from {before_dbm} to {after_dbm} dBm.",
    "router_moved": "The router was moved.", "router_home": "The router is back home.",
    "cam_on": "The camera is on.", "cam_stalled": "The camera has stalled.", "cam_off": "The camera is off.",
}
ARMED_SENTENCES = {"armed": "Armed: this space should be empty now.", "disarmed": "Disarmed.",
                   "intrusion": "Someone is here while armed, in zone {zone}."}
NO_NODE = {"object_on": "Something new is sitting in the room.", "object_off": "The new object is gone."}


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


def near(nodes: dict, xy):
    """The closest node within NEAR_M of xy, or None when no node is that close."""
    node = min(nodes, key=lambda n: math.dist(nodes[n], xy))
    return node if math.dist(nodes[node], xy) <= NEAR_M else None


def object_drop(o: dict, a, b) -> float:
    return fake.drop((o["x"], o["y"]), a, b, o.get("drop_db", 6.0), o.get("width_m", 0.25))


class Brain:
    """Feed it the fake feed's events with `see`, ask for a `state(t)`, read `events`."""

    def __init__(self, path: dict, rate: float = 15.0, start_ms: int = 0):
        self.path, self.rate, self.start_ms = path, rate, start_ms
        self.readings = {fake.link_id(*l): deque() for l in fake.LINKS}   # (t, dbm), last few seconds
        self.last_dbm, self.stale_since, self.ok_since, self.blind = {}, {}, {}, set()
        self.off_since, self.back_since, self.jumped = {}, {}, set()   # the jump rule
        self.recent, self.anchor = deque(maxlen=RECENT), ("none", 0)   # last decisions as (kind, zone, moving)
        self.still_s = self.alert_s = 0.0
        self.last_t = self.zone = None
        self.checkin = self.narration = self.advice = None
        self.waves_done, self.moved_at, self.advice_off = set(), None, False
        self.before = {"present": False, "zone": 0, "alert": "none", "cam": "on", "spot": "S-home",
                       "blind": set(), "objects": {}, "baseline": False, "trained": False}
        self.events, self.n_events = [], 0
        self.armed, self.intruded = False, False   # section 6, Armed: the space should be empty
        self.demo = []   # every event since the last reset, for the recap

    def see(self, event: dict) -> None:
        if event["type"] == "rssi":
            self.readings[event["link"]].append((event["t"], event["dbm"]))

    def command(self, msg: dict) -> None:
        """A screen -> brain cmd. reset_alert and reset change things; the rest are accepted."""
        t = self.last_t or 0.0
        if msg.get("cmd") == "arm":   # arm {on: true|false}: "this space should be empty now"
            self._arm(t, bool((msg.get("args") or {}).get("on")))
        if msg.get("cmd") in ("reset_alert", "reset"):
            self.alert_s = 0.0
        if msg.get("cmd") == "reset":
            self._arm(t, False)
        if msg.get("cmd") == "reset":   # between judges: also the still timer, check-in, advice, narration
            self.still_s, self.checkin, self.narration = 0.0, None, None
            self.advice, self.advice_off = None, True
            # The `reset` event (section 5), then the narrator's end-of-demo recap: its template
            # recap of what happened since the last reset, as the board sends when the model is slow.
            demo, self.demo = self.demo, []
            t = self.last_t or 0.0
            self._event(t, "reset")
            text = recap_template(demo)
            if text:
                self.narration = {"text": text, "event_id": f"e{self.n_events}", "t": self._ms(t),
                                  "source": "template", "gen_ms": 0}

    def _arm(self, t: float, on: bool) -> None:
        if on != self.armed:
            self.armed, self.intruded = on, False
            self._event(t, "armed" if on else "disarmed")

    def _intrusion(self, t: float, pred) -> None:
        """Section 6: while armed, one intrusion each time a person appears (person holds the majority
        of the last 10 decisions, after it didn't). Never while blind or with no prediction."""
        person = sum(k == "person" for k, _, _ in self.recent) > len(self.recent) / 2
        if not self.armed or pred is None:
            return
        if person and not self.intruded:
            self.intruded = True
            self._event(t, "intrusion", zone=self.anchor[1] or None)
        elif not person:
            self.intruded = False

    def _ms(self, t: float) -> int:
        return self.start_ms + round(t * 1000)

    def _median(self, link: str, t0: float, t1: float):
        values = [d for at, d in self.readings[link] if t0 <= at < t1]
        return round(median(values), 1) if values else None

    def _links(self, t: float, baseline: bool) -> list:
        out = []
        for tx, rx, kind in fake.LINKS:
            link = fake.link_id(tx, rx, kind)
            q = self.readings[link]
            while q and q[0][0] <= t - 2 * MEDIAN_S:
                q.popleft()
            rate = sum(1 for at, _ in q if at > t - 2.0) / min(2.0, max(t, 1.0 / self.rate))
            if rate < STALE_RATIO * self.rate:
                self.ok_since.pop(link, None)
                if t - self.stale_since.setdefault(link, t) >= BLIND_AFTER_S:
                    self.blind.add(link)
            else:
                self.stale_since.pop(link, None)
                if t - self.ok_since.setdefault(link, t) >= CLEAR_AFTER_S:
                    self.blind.discard(link)
            now = self._median(link, t - 1.0, t + 1e-9)
            if now is not None:
                self.last_dbm[link] = now
            if link not in self.last_dbm:
                continue   # a link is listed once it has a reading
            dbm = self.last_dbm[link]   # a silent link keeps its last level
            base = round(fake.baseline(tx, rx, kind), 1) if baseline else None
            out.append({"id": link, "dbm": dbm, "base_dbm": base,
                        "drop_db": round(base - dbm, 1) if baseline else None,
                        "rate_hz": round(rate, 1), "expected_hz": self.rate if baseline else None,
                        "status": "blind" if link in self.blind else "stale" if link in self.stale_since else "ok",
                        "why": 0.0})
        return out

    def _steady(self, link: str, since: float, t: float) -> bool:
        """Section 6: the std of the link's 0.5 s means, over the time since it went off base
        (2 s at least, 5 s at most), is under 0.8 dB."""
        span = min(5.0, max(2.0, t - since))
        bins = {}
        for at, dbm in self.readings[link]:
            # The newest half second is left out: when the level comes back, that bin moves first,
            # and a drop that has just ended must not read as an unsteady one for a moment.
            if t - span < at <= t - 0.5:
                bins.setdefault(int((t - at) / 0.5), []).append(dbm)
        means = [mean(v) for v in bins.values()]
        return len(means) >= 2 and pstdev(means) < STEADY_DB

    def _jumps(self, t: float, links: list, kind: str, home: bool) -> None:
        """Section 6: a link is blind when nobody and nothing is there and it has sat more than 6 dB
        off its base for 3 s. A reading below base that holds steady is an object, not a jump."""
        for l in links:
            link, drop = l["id"], l["drop_db"]
            if drop is None or abs(drop) <= JUMP_DB or kind != "none" or not home:
                self.off_since.pop(link, None)
                if link in self.jumped and t - self.back_since.setdefault(link, t) >= CLEAR_AFTER_S:
                    self.jumped.discard(link)
                    self.back_since.pop(link, None)
                continue
            self.back_since.pop(link, None)
            since = self.off_since.setdefault(link, t)
            if t - since >= BLIND_AFTER_S and not (drop > 0 and self._steady(link, since, t)):
                self.jumped.add(link)
        for l in links:
            if l["id"] in self.jumped:
                l["status"] = "blind"

    def _advise(self, t: float, things: list, spot: str, nodes: dict, links: list) -> None:
        """Section 6: an object that stays 5 s within 0.5 m of the router link gets advice, but only
        while pi5>unoq:wifi is dropping now (drop_db >= 3 dB; no row or a null drop means no advice)."""
        home = fake.NODES
        wifi = next((l for l in links if l["id"] == WIFI), None)
        dropping = wifi is not None and wifi.get("drop_db") is not None and wifi["drop_db"] >= ADVICE_DROP_DB
        close = [o for o in things if t - o.get("t_on", 0.0) >= STATIC_AFTER_S
                and fake.dist_to_link((o["x"], o["y"]), home["pi5"], home["unoq"]) <= ADVICE_WITHIN_M]
        if spot != "S-home" and self.moved_at is None:
            self.moved_at = t
        if spot == "S-home":
            if self.moved_at is not None or not close or not dropping:   # back home, nothing in the way, or the link has recovered
                self.advice, self.advice_off = None, False
            self.moved_at = None
        if self.advice is None and close and dropping and spot == "S-home" and not self.advice_off:
            o = close[0]
            # the spot whose new link the object blocks least; west wins a tie
            to = min(("S-W30", "S-E30"), key=lambda s: round(object_drop(o, fake.ROUTER_SPOTS[s], home["unoq"]), 3))
            dx, dy = (round(a - b, 2) for a, b in zip(fake.ROUTER_SPOTS[to], home["pi5"]))
            node = near(home, (o["x"], o["y"]))
            where = {None: "On the router's link, an obstruction", "pi5": "An obstruction next to the router"}.get(
                node, f"An obstruction next to the {node} node")
            self.advice = {
                "id": f"a{self.n_events + 1}", "cause": "obstruction", "near": node, "xy_m": [o["x"], o["y"]],
                "link": WIFI, "to_spot": to, "move_m": [dx, dy],
                "dist_change_m": round(math.dist(fake.ROUTER_SPOTS[to], home["unoq"])
                                       - math.dist(home["pi5"], home["unoq"]), 2),
                "text": f"{where} is blocking its link to the receiver. "
                        f"Move the router {round(abs(dx) * 100)} cm {'west' if dx < 0 else 'east'}.",
                "before_dbm": None, "after_dbm": None,
                "why": [fake.link_id(*l) for l in fake.LINKS if object_drop(o, home[l[0]], home[l[1]]) > 1.0]}
            self._event(t, "advice", link=WIFI, node=node)
        if self.advice and self.moved_at is None:      # before the move: the last 3 s
            recent = self._median(WIFI, t - MEDIAN_S, t + 1e-9)   # never null: fall back to the last level
            self.advice["before_dbm"] = self.last_dbm.get(WIFI) if recent is None else recent
        elif (self.advice and self.advice["after_dbm"] is None
              and t >= self.moved_at + RESULT_WAIT_S + MEDIAN_S):   # 3 s, starting 2 s after the move
            self.advice["after_dbm"] = self._median(WIFI, self.moved_at + RESULT_WAIT_S, t + 1e-9)
            self._event(t, "advice_result", link=WIFI, before_dbm=self.advice["before_dbm"],
                        after_dbm=self.advice["after_dbm"])

    def state(self, t: float) -> dict:
        path = self.path
        dt = 0.0 if self.last_t is None else t - self.last_t
        self.last_t = t
        baseline, trained = t >= BASELINE_AT_S, t >= TRAINED_AT_S
        pos = fake.position(path.get("person") or [], t)
        moving = fake.is_moving(path.get("person") or [], t)
        zone = fake.zone_of(*pos) if pos else 0
        spot = fake.latest(path.get("router"), t, "spot", "S-home")
        cam = fake.latest(path.get("camera"), t, "state", "on")
        nodes = {**fake.NODES, "pi5": fake.ROUTER_SPOTS[spot]}
        # an object shows 2 s after it lands, and goes about 1 s after it is taken away (its link's
        # static part comes down at once, whoever else is in the room)
        things = [o for o in path.get("objects") or []
                  if o.get("t_on", 0.0) + OBJECT_AFTER_S <= t < o.get("t_off", math.inf) + OBJECT_GONE_S]
        kind = "person" if pos else "object" if things else "none"

        links = self._links(t, baseline)
        stale = [l["id"] for l in links if l["status"] != "ok"]
        if baseline:
            self._jumps(t, links, kind, spot == "S-home")
        blind = sorted(self.blind | self.jumped) if baseline else []
        health = {"status": "blind" if blind else "degraded" if stale else "ok", "blind": blind,
                  "reason": "rate" if stale else "jump" if blind else None}

        # how much of each link's drop the person explains, for "why"
        share = {fake.link_id(*l): fake.drop(pos, nodes[l[0]], nodes[l[1]], fake.PERSON_DROP_DB, fake.PERSON_WIDTH_M)
                 if pos else 0.0 for l in fake.LINKS}
        total = sum(share.values())
        for l in links:
            l["why"] = round(share[l["id"]] / total, 2) if total > 0.5 else 0.0
        why = [k for k, v in sorted(share.items(), key=lambda kv: -kv[1]) if v > 1.0][:2]

        # The still timer is judged on smoothed decisions (section 6). A decision can be wrong for a
        # moment: a path's "flickers" make the fake brain say moving while the person stands still.
        moving = moving or (bool(pos) and any(fake.active(f, t) for f in path.get("flickers") or []))
        self.recent.append((kind, zone, moving))
        top, votes = Counter((k, z) for k, z, _ in self.recent).most_common(1)[0]
        if top != self.anchor and votes > len(self.recent) / 2:   # another zone or kind holds the majority
            self.anchor, self.still_s, self.alert_s = top, 0.0, 0.0
        run = 0
        for _, _, was_moving in reversed(self.recent):
            if not was_moving:
                break
            run += 1
        still = self.anchor[0] == "person" and run < MOVING_RUN
        if run >= MOVING_RUN:                            # 5 moving decisions in a row (0.5 s)
            self.still_s = self.alert_s = 0.0
        elif still:
            self.still_s += dt
        self.zone = zone
        limit = STILL_ALERT_S.get(self.anchor[1])
        if not (still and limit):
            self.alert_s = 0.0
        elif not blind:                                  # alert timers pause while blind
            self.alert_s += dt
        for i, w in enumerate(path.get("waves") or []):  # a wave becomes a check-in
            if i not in self.waves_done and t >= w.get("t_on", 0.0) + CHECKIN_AFTER_S and fake.active(w, t):
                self.waves_done.add(i)
                self.checkin = {"t": self._ms(t), "link": w.get("link", WIFI)}
                self.alert_s = 0.0
                self._event(t, "checkin", link=self.checkin["link"])
        if baseline:
            self._advise(t, things, spot, nodes, links)

        pred = None
        if trained and not blind and spot == "S-home":
            probs = [0.03] * (len(STILL_ALERT_S) + 1)   # empty, then one per zone
            probs[zone] = 0.88
            pred = {"present": bool(pos), "kind": kind, "zone": zone, "zone_set": [zone] if pos else [],
                    "probs": probs, "motion": ("moving" if moving else "still") if pos else None,
                    "still_s": round(self.still_s, 1), "why": why}
        alert = dict(IDLE_ALERT)
        if pred and still and limit:
            alert = {"state": "check_on" if self.alert_s >= limit else "counting", "zone": self.anchor[1],
                     "still_s": round(self.alert_s, 1), "limit_s": limit}

        objects = [{"xy_m": [o["x"], o["y"]],
                    "near": near(nodes, (o["x"], o["y"])),
                    "since_s": round(t - o.get("t_on", 0.0), 1),
                    "drop_db": round(max(object_drop(o, nodes[l[0]], nodes[l[1]]) for l in fake.LINKS), 1)}
                   for o in things] if baseline else []
        xray = {**GRID,
                "moving_db": blob([(*pos, 6.0)] if pos and moving else []),
                "static_db": blob([(o["x"], o["y"], o.get("drop_db", 6.0)) for o in things
                                   if t - o.get("t_on", 0.0) >= STATIC_AFTER_S]),
                "n_links": len(links) - len(blind)} if baseline else None

        self._intrusion(t, pred)
        self._diff(t, {"present": bool(pos), "zone": zone, "alert": alert["state"], "cam": cam, "spot": spot,
                       "blind": set(blind), "objects": {tuple(o["xy_m"]): o["near"] for o in objects},
                       "baseline": baseline, "trained": trained}, pred is not None)
        return {"type": "state", "t": t, "cam": cam, "router": spot, "links": links, "health": health,
                "pred": pred, "objects": objects, "xray": xray, "alert": alert, "checkin": self.checkin,
                "advice": dict(self.advice) if self.advice else None, "narration": self.narration,
                "teacher": {"present": bool(pos), "zone": zone,
                            "motion": ("moving" if moving else "still") if pos else None} if cam == "on" else None,
                "model": {"trained": trained, "ver": "sim" if trained else None, "train_s": None,
                          "ms_per_decision": None, "windows": 0, "train_sessions": [], "training": None},
                "board": {"cpu_temp_c": None, "cpu_mhz": None, "cpu_pct": None},
                **({"armed": True} if self.armed else {})}   # section 5: missing means false

    def _event(self, t: float, kind: str, **info) -> None:
        info = {k: v for k, v in info.items() if v is not None}   # an unknown node is left out, not sent as null
        self.n_events += 1
        self.events.append({"type": "event", "t": t, "id": f"e{self.n_events}", "kind": kind, "info": info})
        if kind == "reset":
            return   # no sentence of its own: the recap follows
        if kind in ARMED_SENTENCES:
            self.narration = {"text": ARMED_SENTENCES[kind].format(zone=info.get("zone", "")).replace(" in zone .", "."),
                              "event_id": f"e{self.n_events}", "t": self._ms(t), "source": "template", "gen_ms": 0}
            self.demo.append({"kind": kind, "info": info, "t": self._ms(t)})
            return
        self.demo.append({"kind": kind, "info": info, "t": self._ms(t)})
        sentence = NO_NODE[kind] if kind in NO_NODE and info.get("node") is None else SENTENCES[kind]
        self.narration = {"text": sentence.format(**info), "event_id": f"e{self.n_events}",
                          "t": self._ms(t), "source": "template", "gen_ms": 0}

    def _diff(self, t: float, now: dict, has_pred: bool) -> None:
        was, self.before = self.before, now
        for step in ("baseline", "trained"):
            if now[step] and not was[step]:
                self._event(t, "baseline_done" if step == "baseline" else "trained")
        if not has_pred:   # no prediction, no news about people: remember what was last known
            now["present"], now["zone"] = was["present"], was["zone"]
        elif now["present"] and not was["present"]:
            self._event(t, "enter", zone=now["zone"])
        elif was["present"] and not now["present"]:
            self._event(t, "exit", zone=was["zone"])
        elif now["present"] and now["zone"] != was["zone"]:
            self._event(t, "zone_change", zone=now["zone"])
        if (now["alert"] == "check_on") != (was["alert"] == "check_on"):
            self._event(t, "alert_on" if now["alert"] == "check_on" else "alert_off", zone=now["zone"])
        if now["cam"] != was["cam"]:
            self._event(t, "cam_" + now["cam"])
        if now["spot"] != was["spot"]:
            self._event(t, "router_home" if now["spot"] == "S-home" else "router_moved")
        for link in sorted(now["blind"] - was["blind"]):
            self._event(t, "blind_on", link=link)
        for link in sorted(was["blind"] - now["blind"]):
            self._event(t, "blind_off", link=link)
        for xy in sorted(now["objects"].keys() - was["objects"].keys()):   # objects are told apart by where they are
            self._event(t, "object_on", node=now["objects"][xy])
        for xy in sorted(was["objects"].keys() - now["objects"].keys()):
            self._event(t, "object_off", node=was["objects"][xy])


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

    yield from due(0.0)   # the first state goes out before any reading has arrived
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
