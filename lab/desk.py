"""The desk strip with people walking past. SIMULATED, dev only.

    python -m lab.desk --seed 3 --rate 6          # one session, prints its metrics
    python -m lab.desk --seed 3 --rate 6 --json

The layout is the desk strip of the draft contract (lab/desk_nodes.json, a copy
of radio/nodes.json from PR #415 @ aabebe9): five nodes on our desk, twelve
links, two zones in a 1.6 x 0.6 m strip of the judges' aisle. The link physics
is lab/rf.py's (knife-edge shadow, a reflected ray per body, hall fading), here
with any number of bodies at once.

One session:
  A. "tonight, quiet room": baseline, three walkers recorded with the camera on
     (zone centres, the middle, 40 cm back from the desk, wandering, stepping
     out), an empty recording, optionally someone walking the aisle outside the
     strip, then train.
  B. "at the judging desk", camera unplugged: the kit is set down again (every
     link's level shifts), a new baseline with `baseline {keep_model: true}`
     when the brain has it, then
       - an empty strip (the arrival screen),
       - a judging visit: walk up, stop 40 cm short, step up, step left, step
         right, stand still 15 s, leave (see VISITS for the other kinds),
       - a second visitor who paces their half of the strip and never stands
         (the alert must not fire),
       - armed: empty, then somebody steps in and stays, somebody cuts through
         the strip, somebody brushes an arm tip.
     All through B people walk the aisle (Poisson, `rate` a minute, 0.6-1.4
     m/s), neighbours stand beyond each end of the strip, and readings are lost.

Every message goes through the real brain.core.Brain. The decisions it hands to
its own alert and armed rules are logged, and replay_* re-run those rules with
other settings on exactly that stream (the default settings give back the
brain's own events; a test checks it).

What to trust: which lane touches which link and for how long, and how the
brain's logic turns that into events. Not: absolute dB closer than 0.3 m to an
antenna, people behind a beacon, 300 phones on the band. Rank settings with it;
its percentages are not accuracies.
"""
from __future__ import annotations

import argparse
import copy
import inspect
import json
import logging
import math
import statistics
import time
from collections import deque
from pathlib import Path

import numpy as np

from lab import rf

ROOT = Path(__file__).resolve().parent.parent
DESK_JSON = Path(__file__).resolve().parent / "desk_nodes.json"
LAYOUT_PIN = "PR #415 @ aabebe9"
DT = rf.DT
STRIP = (1.6, 0.6)
SPLIT_X = 0.8
DESK_EDGE_Y = 0.6
AISLE_FAR_Y = -0.35          # the next row's desk edge: the aisle is 0.95 m wide
CROSS = ("west>pi5b:ble", "west>unoq:ble", "east>unoq:ble", "east>pi5b:ble")
ZONE_LINKS = {1: ("west>pi5b:ble", "west>unoq:ble"), 2: ("east>unoq:ble", "east>pi5b:ble")}
SIX = ("pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble")
VISITS = ("standard", "back40", "two", "backpack", "kid", "lean")


def desk_doc(reach_m: float = 0.35) -> dict:
    """The desk layout's nodes.json with the arm tips `reach_m` out over the aisle."""
    doc = json.loads(DESK_JSON.read_text(encoding="utf-8"))
    for n in doc["nodes"]:
        if n["id"] in ("east", "west"):
            n["xyz_m"][1] = round(DESK_EDGE_Y - reach_m, 3)
    return doc


def link_set(name: str, doc: dict) -> tuple:
    every = tuple(lk["id"] for lk in doc["links"])
    return {"twelve": every, "six": SIX, "cross": CROSS,
            "cross+ends": CROSS + ("east>pi5:ble", "west>pi5:ble")}[name]


class Lay:
    def __init__(self, doc):
        self.doc = doc
        self.nodes = {n["id"]: tuple(n["xyz_m"][:2]) for n in doc["nodes"]}
        self.links = [lk["id"] for lk in doc["links"]]
        self.ends = {lk["id"]: (lk["tx"], lk["rx"]) for lk in doc["links"]}
        self.kind = {lk["id"]: lk["kind"] for lk in doc["links"]}
        self.tip_y = self.nodes["west"][1]


def in_strip(x, y):
    return (x >= 0) & (x <= STRIP[0]) & (y >= 0) & (y <= STRIP[1])


# ---------------------------------------------------------------- the scene

class Body:
    """One person (or a backpack, or a hand) from t0 on, one position every DT."""

    def __init__(self, tag, t0, x, y, person: rf.Person, scatter=1.0):
        self.tag, self.t0 = tag, float(t0)
        self.x, self.y = np.asarray(x, float), np.asarray(y, float)
        self.t1 = self.t0 + len(self.x) * DT
        self.width, self.depth, self.height = person.width_m, person.depth_db, person.height_m
        self.scatter = scatter

    def at(self, t):
        i = np.clip(((np.asarray(t) - self.t0) / DT).astype(int), 0, len(self.x) - 1)
        return self.x[i], self.y[i]

    def strip_spans(self):
        """[(t_in, t_out)] while the body's centre is inside the strip."""
        inside = in_strip(self.x, self.y)
        return _runs(inside, self.t0)

    def abeam_span(self):
        """(t_in, t_out) while the body is level with the strip (0 <= x <= 1.6), or None."""
        r = _runs((self.x >= 0) & (self.x <= STRIP[0]), self.t0)
        return (r[0][0], r[-1][1]) if r else None


def _runs(mask, t0):
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        elif not m and start is not None:
            out.append((t0 + start * DT, t0 + i * DT))
            start = None
    if start is not None:
        out.append((t0 + start * DT, t0 + len(mask) * DT))
    return out


class Scene:
    """Bodies, commands and spans on one clock."""

    def __init__(self, rng, env):
        self.rng, self.env = rng, env
        self.t = 0.0
        self.bodies: list = []
        self.cmds: list = []
        self.spans: dict = {}
        self.cam_on: list = []       # (t0, t1) the camera is plugged in
        self.modes: list = []        # (t, label_mode)
        self.focus: list = []        # bodies the camera labels

    def cmd(self, c, **args):
        self.cmds.append((self.t, c, args))

    def span(self, tag, t0, t1=None):
        self.spans.setdefault(tag, []).append((t0, self.t if t1 is None else t1))

    def idle(self, s):
        self.t += s

    def act(self, tag, person, at, moves, focus=False, advance=True, t0=None, scatter=1.0):
        """A scripted person: `moves(sc)` drives an rf.Script that starts at `at`."""
        sc = rf.Script(self.rng, self.env)
        sc.enter(person, at=at)
        moves(sc)
        body = Body(tag, self.t if t0 is None else t0, sc.x, sc.y, person, scatter)
        body.marks = [(body.t0 + t, k, i) for t, k, i in sc.marks]
        self.bodies.append(body)
        if focus:
            self.focus.append(body)
        if advance:
            self.t = body.t1
        return body


def _passer(rng, t_mid, lane_y, person, tag="passer"):
    """Somebody walking the aisle past the desk; t_mid is when they are level with x = 0.8."""
    v = rng.uniform(0.6, 1.4)
    d = rng.choice([-1.0, 1.0])
    x0, x1 = (SPLIT_X - 3.8 * d, SPLIT_X + 3.8 * d)
    n = int(abs(x1 - x0) / v / DT)
    s = np.arange(n) * DT
    x = x0 + d * v * s
    y = lane_y + 0.02 * np.sin(2 * np.pi * 0.9 * s + rng.uniform(0, 6.3)) + 0.03 * np.sin(2 * np.pi * s / 6 + rng.uniform(0, 6.3))
    b = Body(tag, t_mid - 3.8 / v, x, y, person)
    b.lane, b.speed = float(lane_y), float(v)
    return b


def _neighbour(rng, t0, t1, x_centre, person):
    """Somebody at the next team's desk: stands, shifts every few seconds."""
    n = int((t1 - t0) / DT)
    x, y = np.empty(n), np.empty(n)
    k, cx, cy = 0, x_centre + rng.uniform(-0.25, 0.25), rng.uniform(-0.1, 0.4)
    while k < n:
        m = int(rng.uniform(4, 20) / DT)
        x[k:k + m], y[k:k + m] = cx, cy
        k += m
        cx = x_centre + rng.uniform(-0.25, 0.25)
        cy = float(np.clip(cy + rng.uniform(-0.2, 0.2), -0.2, 0.45))
    a = math.exp(-DT / 2.0)
    from scipy.signal import lfilter
    sw = lfilter([1.0], [1.0, -a], rng.normal(0, 0.03 * math.sqrt(1 - a * a), (n, 2)), axis=0)
    return Body("neighbour", t0, x + sw[:, 0], y + sw[:, 1], person)


SCENE = {
    "rate": 6.0,            # people walking past per minute, phase B
    "reach_m": 0.35,        # arm tips this far out from the desk's judge edge
    "visit": "standard",
    "neighbours": 1,        # people standing beyond each end of the strip
    "neighbour_gap_m": 1.0,
    "brush_p": 0.08,        # share of passers who squeeze past touching an arm tip
    "train_aisle": False,   # tonight's recordings include somebody walking the aisle outside the strip
    "train_still_s": 5.0,
    "train_empty_s": 12.0,  # tonight's empty-strip recording
    "empty_between": False, # the empty recording is split: a third of it after each walker
    "train_back": True,     # tonight's walkers also stand 40 cm back from the desk and wander the strip's aisle side
    "baseline_s": 20,       # the desk baseline's length (20 = the contract's)
    "place_db": 3.0,        # how far each link's level moves when the kit is set down at the judging desk
    "loss": 0.1,            # mean share of readings lost at the judging desk
    "k_db_desk": 12.0,      # hall fading at judging (tonight's quiet room uses env.k_db)
    "strip_clear_baseline": True,   # the operator keeps the strip itself empty during the desk baseline
}


def build(seed: int, env: rf.Env, scene: dict = None):
    """The whole session: a Scene and the plan (phase times, people)."""
    p = dict(SCENE, **(scene or {}))
    rng = np.random.default_rng(seed)
    S = Scene(rng, env)
    tip_y = DESK_EDGE_Y - p["reach_m"]
    walkers = [rf.Person.draw(rng) for _ in range(3)]
    aisle_x = lambda: float(rng.choice([-1.2, 2.8]))   # noqa: E731

    # ---- A: tonight, quiet room, camera on
    cam0 = S.t
    S.idle(1.0)
    S.cmd("baseline")
    S.idle(120.0)                # the operator waits: a link silent for 1 s starts the 20 s over
    for k, w in enumerate(walkers):
        S.cmd("record_start", session=f"t{k}", purpose="train", walker=f"w{k}")
        S.cmd("label_mode", mode="person")
        S.modes.append((S.t, "person"))
        S.idle(1.0)

        def tour(sc):
            spots = [(0.4, 0.35), (1.2, 0.35), (0.8, 0.35), (rng.uniform(0.3, 1.3), 0.15 if p["train_back"] else 0.4),
                     (rng.uniform(0.2, 0.6), 0.45), (rng.uniform(1.0, 1.4), 0.45)]
            for i in rng.permutation(len(spots)):
                sc.walk_to(spots[i][0] + rng.uniform(-0.1, 0.1), spots[i][1] + rng.uniform(-0.06, 0.06))
                sc.stand(p["train_still_s"] * rng.uniform(0.8, 1.2))
            for _ in range(6):
                sc.walk_to(rng.uniform(0.1, 1.5), rng.uniform(0.08 if p["train_back"] else 0.3, 0.5))
                sc.stand(rng.uniform(0.0, 1.2))
            sc.walk_to(rng.uniform(0.3, 1.3), -0.5)      # steps back out of the strip
            sc.stand(3.0)
            sc.walk_to(rng.uniform(0.3, 1.3), 0.35)
            sc.stand(2.0)
            sc.walk_to(aisle_x(), -0.15)
        S.act("walker", w, (aisle_x(), -0.15), tour, focus=True)
        S.idle(1.5)
        S.cmd("record_stop")
        if p["empty_between"]:
            S.cmd("record_start", session=f"e{k}", purpose="train", walker=None)
            S.idle(p["train_empty_s"] / len(walkers))
            S.cmd("record_stop")
    if not p["empty_between"]:
        S.cmd("record_start", session="e0", purpose="train", walker=None)
        S.idle(p["train_empty_s"])
        S.cmd("record_stop")
    if p["train_aisle"]:
        S.cmd("record_start", session="a0", purpose="train", walker="w0")
        for _ in range(5):
            b = _passer(rng, S.t + 5.0, rng.uniform(-0.3, -0.06), walkers[0], tag="walker")
            b.t0 = S.t
            b.t1 = b.t0 + len(b.x) * DT
            S.bodies.append(b)
            S.focus.append(b)
            S.t = b.t1 + 1.0
        S.cmd("record_stop")
    S.cmd("label_mode", mode="off")
    S.modes.append((S.t, "off"))
    S.cmd("train")
    S.idle(3.0)
    S.cam_on.append((cam0, S.t))

    # ---- B: at the judging desk, camera unplugged
    tB = S.t
    S.idle(3.0)
    S.cmd("baseline", keep_model=True)
    t_base = S.t
    S.idle(p["baseline_s"] + 30.0)   # same here; what is left of this is an empty strip
    S.span("desk_baseline", t_base, t_base + p["baseline_s"] + 3.0)
    t0 = S.t
    S.idle(30.0)
    S.span("arrival", t0)

    judge = rf.Person.draw(rng)
    kind = p["visit"]
    if kind == "kid":
        judge = rf.Person.draw(rng, height_m=float(rng.uniform(1.1, 1.35)), width_m=0.3)
    xs = float(rng.uniform(0.5, 1.1))
    back_y, up_y = DESK_EDGE_Y - 0.4 - 0.12, DESK_EDGE_Y - 0.2     # body centre: toes 40 cm back / at the desk
    if kind == "lean":
        up_y = DESK_EDGE_Y - 0.1
    stages = {}

    def visit(sc):
        def stage(name, s):
            a = sc.t
            sc.stand(s)
            stages[name] = (a, sc.t)
        sc.walk_to(xs, back_y)
        stage("short", rng.uniform(4.5, 6.0))
        if kind == "back40":            # never steps up: everything happens 40 cm back
            y = back_y
        else:
            y = up_y
            sc.walk_to(xs, y)
        stage("up", rng.uniform(3.5, 5.0))
        sc.walk_to(xs - 0.45, y)
        stage("left", rng.uniform(3.5, 5.0))
        sc.walk_to(xs + 0.45, y)
        stage("right", 1.0)
        stage("still", 15.0)
        sc.walk_to(aisle_x(), -0.15)
    start = (aisle_x(), -0.15)
    b = S.act("visit1", judge, start, visit, advance=False)
    for name, (a, c) in stages.items():
        S.span(name, b.t0 + a, b.t0 + c)
    if kind == "backpack":             # a pack on the back: a second body 25 cm towards the aisle
        pack = rf.Person(height_m=1.45, width_m=0.35, depth_db=5.0)
        S.bodies.append(Body("pack", b.t0, b.x, b.y - 0.25, pack, scatter=0.5))
    if kind == "lean":                 # forearms on the desk's judge edge while at the desk
        arm = rf.Person(height_m=1.1, width_m=0.25, depth_db=4.0)
        a, c = stages["up"][0], stages["still"][1]
        i0, i1 = int(a / DT), int(c / DT)
        S.bodies.append(Body("arms", b.t0 + a, b.x[i0:i1], np.full(i1 - i0, DESK_EDGE_Y), arm, scatter=0.5))
    if kind == "two":                  # a second judge beside the first, a step back, shifting a little
        mate = rf.Person.draw(rng)
        side = -0.55 if xs > 0.8 else 0.55

        def beside(sc):
            sc.walk_to(xs + side, back_y)
            while sc.t < (len(b.x) * DT) - 6.0:
                sc.stand(rng.uniform(3.0, 7.0))
                sc.walk_to(float(np.clip(xs + side + rng.uniform(-0.15, 0.15), 0.1, 1.5)),
                           back_y + rng.uniform(0.0, 0.2))
            sc.walk_to(start[0], -0.2)
        S.act("visit1b", mate, (start[0], -0.3), beside, advance=False)
    S.t = b.t1
    S.span("visit1", b.t0)
    S.idle(2.0)
    S.cmd("reset")
    S.idle(3.0)

    fid = rf.Person.draw(rng, speed=float(rng.uniform(0.5, 0.7)))

    def fidget(sc):
        sc.walk_to(rng.uniform(0.1, 0.2), up_y)
        a = sc.t
        while sc.t - a < 14.0:          # paces the west half of the strip, never standing
            sc.walk_to(rng.uniform(0.6, 0.72), up_y + rng.uniform(-0.05, 0.05))
            sc.walk_to(rng.uniform(0.08, 0.2), up_y + rng.uniform(-0.05, 0.05))
        stages["fidget"] = (a, sc.t)
        sc.walk_to(aisle_x(), -0.15)
    b2 = S.act("visit2", fid, (aisle_x(), -0.15), fidget)
    S.span("fidget", b2.t0 + stages["fidget"][0], b2.t0 + stages["fidget"][1])
    S.span("visit2", b2.t0)
    S.idle(2.0)
    S.cmd("reset")
    S.idle(4.0)

    S.cmd("arm", on=True)
    t0 = S.t
    S.idle(60.0)
    S.span("armed_empty", t0)
    intr = rf.Person.draw(rng)

    def step_in(sc):
        sc.walk_to(rng.uniform(0.3, 1.3), rng.uniform(0.3, 0.45))
        sc.stand(rng.uniform(5.0, 8.0))
        sc.walk_to(aisle_x(), -0.15)
    bi = S.act("intruder", intr, (aisle_x(), -0.15), step_in)
    S.span("intruder", bi.t0)
    S.idle(8.0)
    bt = _passer(rng, S.t + 4.0, rng.uniform(0.3, 0.4), rf.Person.draw(rng), tag="through")
    S.bodies.append(bt)
    S.span("through", bt.t0, bt.t1)
    S.t = bt.t1 + 6.0
    bb = _passer(rng, S.t + 4.0, tip_y - rng.uniform(0.0, 0.1), rf.Person.draw(rng), tag="brush")
    S.bodies.append(bb)
    S.span("brush", bb.t0, bb.t1)
    S.t = bb.t1 + 6.0
    S.cmd("arm", on=False)
    S.idle(2.0)
    T = S.t

    # ---- people around, all through B
    scripted = [x for x in S.bodies if x.tag in ("visit1", "visit1b", "visit2", "intruder", "through", "brush")]
    n = rng.poisson(p["rate"] * (T - tB) / 60.0)
    base_span = S.spans["desk_baseline"][0]
    for t_mid in np.sort(rng.uniform(tB + 2.0, T - 2.0, n)):
        lane = rng.uniform(-0.15, tip_y - 0.15)        # body edge at most 5 cm past the arm tip
        tag = "passer"
        if rng.random() < p["brush_p"]:
            lane, tag = tip_y - rng.uniform(0.0, 0.1), "passer_brush"
        for sb in scripted:                            # squeeze behind whoever stands at the desk
            if sb.t0 <= t_mid < sb.t1 and sb.tag not in ("through", "brush"):
                sx, sy = sb.at(t_mid)
                if 0 <= sx <= STRIP[0] and sy > -0.1:
                    lane, tag = min(lane, max(float(sy) - 0.45, -0.17)), "passer"
        if p["strip_clear_baseline"] and base_span[0] - 3 <= t_mid <= base_span[1] + 3:
            lane, tag = min(lane, -0.03), "passer"     # kept out of the strip itself during the baseline
        S.bodies.append(_passer(rng, float(t_mid), float(lane), rf.Person.draw(rng), tag=tag))
    for end_x in (-p["neighbour_gap_m"], STRIP[0] + p["neighbour_gap_m"]):
        for _ in range(int(p["neighbours"])):
            S.bodies.append(_neighbour(rng, tB, T, end_x - 0.3 * np.sign(0.8 - end_x) * rng.uniform(0, 1),
                                       rf.Person.draw(rng)))
    plan = {"tB": tB, "T": T, "scene": p, "tip_y": tip_y, "stages": stages}
    return S, plan


# ---------------------------------------------------------------- the radio

class DeskRadio:
    """Every link's readings and the camera's labels for a Scene."""

    def __init__(self, S: Scene, lay: Lay, plan: dict, seed: int):
        self.S, self.lay, self.env, self.plan = S, lay, S.env, plan
        rng = self.rng = np.random.default_rng(seed + 7919)
        env, T, links = self.env, plan["T"], lay.links
        self.tB = plan["tB"]
        sc = plan["scene"]
        # The hall's scattered power doesn't care how long a link is, but the direct ray does:
        # env.k_db is for a 2 m link (the square's), and a shorter link gets the path-loss difference.
        def k_lin(k_db, lk):
            D = math.dist(lay.nodes[lay.ends[lk][0]], lay.nodes[lay.ends[lk][1]])
            return 10 ** (min(k_db + 10 * env.pl_exp * math.log10(2.0 / D) + rng.normal(0, 2), 40.0) / 10)
        self.k_a = {lk: k_lin(env.k_db, lk) for lk in links}
        self.k_b = {lk: k_lin(sc["k_db_desk"], lk) for lk in links}
        self.offset = {lk: rng.normal(0, env.offset_db) for lk in links}
        self.shift = {lk: rng.normal(0, sc["place_db"]) for lk in links}
        self.chan = {lk: rng.normal(0, env.ble_chan_db, 3) for lk in links}
        self.phase = {lk: rng.uniform(0, 2 * np.pi, 64) for lk in links}
        self.diffuse = {lk: rf._ar1_complex(rng, int(T / 0.05) + 2, 0.05, env.coherence_s) for lk in links}
        nd = int(T) + 2
        self.drift = {k: rf._ou(rng, nd, 1.0, env.drift_tau_s, env.drift_db / math.sqrt(2))
                      for k in links + list(lay.nodes)}
        rxs = sorted({lay.ends[lk][1] for lk in links})
        self.bursts = {(rx, band): rf._bursts(rng, T, env.burst_per_min, env.burst_s)
                       for rx in rxs for band in ("wifi", "ble")}
        nb = int(T / 5.0) + 2          # loss at the judging desk comes and goes, in 5 s blocks, per receiver
        self.loss = {rx: np.clip(sc["loss"] * rng.lognormal(-0.125, 0.5, nb), 0.0, 0.95) for rx in rxs}

    def quiet_dbm(self, link, desk=True):
        tx, rx = self.lay.ends[link]
        kind = self.lay.kind[link]
        ref = rf.REF_DBM["wifi"] if kind == "wifi" else rf.REF_DBM["pi5" if tx in ("pi5", "pi5b") else "phone"]
        D = math.dist(self.lay.nodes[tx], self.lay.nodes[rx])
        chan = float(np.mean(self.chan[link])) if kind == "ble" else 0.0
        return ref - 10 * self.env.pl_exp * math.log10(D) + self.offset[link] + chan + (self.shift[link] if desk else 0.0)

    def level(self, link, t, chan=None):
        """True dBm (before rounding) of a link at sorted times t (s)."""
        lay, env = self.lay, self.env
        tx, rx = lay.ends[link]
        a, b = lay.nodes[tx], lay.nodes[rx]
        lam = rf.LAMBDA_M[lay.kind[link]]
        t = np.asarray(t, float)
        loss = np.zeros(len(t))
        field = np.zeros(len(t), complex)
        ph = self.phase[link]
        for k, body in enumerate(self.S.bodies):
            lo, hi = np.searchsorted(t, [body.t0, body.t1])
            if lo == hi:
                continue
            px, py = body.at(t[lo:hi])
            loss[lo:hi] += rf.shadow_db(px, py, a, b, lam, body.width, body.depth, body.height)
            field[lo:hi] += rf.scatter_field(px, py, a, b, lam, env.scatter * body.scatter, ph[k % 64])
        dif = self.diffuse[link][np.clip((t / 0.05).astype(int), 0, len(self.diffuse[link]) - 1)]
        desk = t >= self.tB
        k_lin = np.where(desk, self.k_b[link], self.k_a[link])
        E = 10 ** (-loss / 20) + field + dif / np.sqrt(k_lin)
        dbm = self.quiet_dbm(link, desk=False) + np.where(desk, self.shift[link], 0.0)
        if lay.kind[link] == "ble":
            dbm = dbm - float(np.mean(self.chan[link]))
        dbm = dbm + 20 * np.log10(np.maximum(np.abs(E), 1e-3))
        for key in (link, tx):
            dbm = dbm + np.interp(t, np.arange(len(self.drift[key])), self.drift[key])
        if chan is not None:
            dbm = dbm + self.chan[link][chan]
        return dbm + self.rng.normal(0, env.meas_db, len(t))

    def _lost(self, rx, t):
        p = np.where(t >= self.tB, self.loss[rx][np.clip((t / 5.0).astype(int), 0, len(self.loss[rx]) - 1)], 0.0)
        return self.rng.random(len(t)) < p

    def readings(self):
        """{link: (t_s, dbm int)}."""
        env, rng, T, lay = self.env, self.rng, self.plan["T"], self.lay
        out = {}
        for lk in lay.links:
            if lay.kind[lk] != "wifi":
                continue
            rx = lay.ends[lk][1]
            polls = np.cumsum(np.full(int(T * env.wifi_poll_hz) + 5, 1 / env.wifi_poll_hz))
            polls = polls + rng.normal(0, env.wifi_jitter_ms / 1000, len(polls))
            polls = np.sort(polls[(polls > 0) & (polls < T)])
            frames = np.cumsum(rng.exponential(1 / env.wifi_frame_hz, int(T * env.wifi_frame_hz * 1.3) + 10))
            frames = frames[frames < T]
            lost = rf._in_any(frames, self.bursts[(rx, "wifi")]) & (rng.random(len(frames)) < 0.9)
            frames = frames[~lost]
            val = self.level(lk, frames)
            k = np.searchsorted(frames, polls, side="right") - 1
            keep = (k >= 0) & ~self._lost(rx, polls)
            keep &= ~(rf._in_any(polls, self.bursts[(rx, "wifi")]) & (rng.random(len(polls)) < 0.3))
            out[lk] = (polls[keep], np.round(val[k[keep]]).astype(int))
        for tx in sorted({lay.ends[lk][0] for lk in lay.links if lay.kind[lk] == "ble"}):
            hz, miss = (env.pi_ble_hz, env.pi_ble_miss) if tx in ("pi5", "pi5b") else (env.phone_hz, env.phone_miss)
            adv = np.cumsum(1 / hz + rng.uniform(0, 0.01, int(T * hz * 1.2) + 10))
            adv = adv[adv < T]
            for lk in lay.links:
                if lay.ends[lk][0] != tx or lay.kind[lk] != "ble":
                    continue
                rx = lay.ends[lk][1]
                heard = rng.random(len(adv)) >= miss
                heard &= ~(rf._in_any(adv, self.bursts[(rx, "ble")]) & (rng.random(len(adv)) < 0.9))
                heard &= ~self._lost(rx, adv)
                ts = adv[heard]
                out[lk] = (ts, np.round(self.level(lk, ts, rng.integers(0, 3, len(ts)))).astype(int))
        return out

    def labels(self):
        """Camera labels while the camera is on: (t_s, fields)."""
        env, rng, S = self.env, self.rng, self.S
        out = []
        bias = rng.normal(0, env.foot_bias_m, 2)
        mode_t = [m[0] for m in S.modes]
        for c0, c1 in S.cam_on:
            frames = c0 + np.cumsum(1 / env.cam_fps + rng.normal(0, 0.01, int((c1 - c0) * env.cam_fps) + 5))
            frames = frames[(frames > c0) & (frames < c1)]
            track, last = [], None
            for n, t in enumerate(frames):
                if rng.random() < env.cam_miss:
                    continue
                k = int(np.searchsorted(mode_t, t, side="right")) - 1
                lab = {"frame": n, "mode": S.modes[k][1] if k >= 0 else "off", "persons_in_frame": 0,
                       "present": False, "zone": 0, "foot_m": None, "motion": None,
                       "conf": round(float(rng.uniform(0.6, 0.95)), 2), "clipped": False}
                who = next((b for b in S.focus if b.t0 <= t < b.t1), None)
                if who is not None and rng.random() >= env.det_miss:
                    if who is not last:
                        track, last = [], who
                    x, y = (float(v) for v in who.at(t))
                    lab["persons_in_frame"] = 1
                    fx, fy = np.array([x, y]) + bias + rng.normal(0, env.foot_noise_m, 2)
                    if in_strip(fx, fy):
                        track.append((t, fx, fy))
                        lab.update(present=True, zone=1 + int(fx >= SPLIT_X), foot_m=[round(fx, 2), round(fy, 2)],
                                   motion=rf._motion(track, t))
                out.append((t, lab))
        return out


def messages(S: Scene, lay: Lay, plan: dict, seed: int, src="sim"):
    """All bus messages of the session, sorted by recv_t; and the radio (for the quiet levels)."""
    radio = DeskRadio(S, lay, plan, seed)
    rng = radio.rng
    seq, out = {}, []

    def put(producer, t_ms, recv_ms, body):
        seq[producer] = seq.get(producer, 0) + 1
        out.append({"v": 2, "type": body.pop("type"), "t": int(t_ms), "seq": seq[producer], "src": src,
                    **body, "recv_t": int(recv_ms)})

    for link, (ts, dbm) in radio.readings().items():
        tx, rx = lay.ends[link]
        lat = rng.uniform(0.5, 3, len(ts)) if rx == "unoq" else rng.uniform(1, 8, len(ts))
        for t, d, la in zip(ts, dbm, lat):
            ms = rf.T0_MS + t * 1000
            put(rx + lay.kind[link], ms, ms + la, {"type": "rssi", "link": link, "kind": lay.kind[link],
                                                  "tx": tx, "rx": rx, "dbm": int(d)})
    for t, lab in radio.labels():
        ms = rf.T0_MS + t * 1000
        put("cam", ms, ms + max(5.0, rng.normal(S.env.cam_latency_ms, 20)), {"type": "label", **lab})
    for s in np.arange(0, plan["T"], 1.0):
        on = any(a <= s < b for a, b in S.cam_on)
        ms = rf.T0_MS + s * 1000
        put("cam", ms, ms + 2, {"type": "cam", "state": "on" if on else "off", "fps": S.env.cam_fps if on else 0.0})
    out.sort(key=lambda m: m["recv_t"])
    return out, radio


# ---------------------------------------------------------------- the real brain

def _brain_modules():
    from lab import overlay
    overlay.install()
    from brain import alert as AL
    from brain import core
    from brain import features as F
    from brain import train as TR
    return AL, core, F, TR


def use_links(links):
    """Point the brain's classifier at a link list (brain/features.py's LINKS and the defaults bound to it)."""
    _, core, F, _ = _brain_modules()
    links = tuple(links)
    F.LINKS = links
    for fn in (F.vector, F.feature_names, F.windows, F.Windower.__init__):
        fn.__defaults__ = (links,)


def quiet_baseline(messages, span_ms=20_000, step_ms=5_000):
    """Candidate: the per-link median over the quietest 20 s of a longer capture.

    Quiet = the 20 s stretch whose links wobble least (sum over links of the std of their 0.5 s means)."""
    rs = [m for m in messages if m.get("type") == "rssi"]
    if not rs:
        return {}
    t0, t1 = rs[0]["recv_t"], rs[-1]["recv_t"]
    best, best_score = None, None
    a = t0
    while True:
        part = [m for m in rs if a <= m["recv_t"] < a + span_ms]
        bins = {}
        for m in part:
            bins.setdefault((m["link"], (m["recv_t"] - a) // 500), []).append(m["dbm"])
        per = {}
        for (link, _), v in bins.items():
            per.setdefault(link, []).append(sum(v) / len(v))
        score = sum(statistics.pstdev(v) for v in per.values() if len(v) > 1)
        if best_score is None or score < best_score:
            best, best_score = part, score
        if a + span_ms >= t1:
            break
        a += step_ms
    by = {}
    for m in best:
        by.setdefault(m["link"], []).append(float(m["dbm"]))
    return {k: statistics.median(v) for k, v in by.items()}


def mean_baseline(messages):
    by = {}
    for m in messages:
        if m.get("type") == "rssi":
            by.setdefault(m["link"], []).append(float(m["dbm"]))
    return {k: sum(v) / len(v) for k, v in by.items()}


def drive(msgs, S: Scene, plan: dict, doc: dict, links, base_est="median"):
    """Feed the session through brain.core.Brain. Returns the decision log and the brain's events."""
    AL, core, F, TR = _brain_modules()
    logging.getLogger("brain").setLevel(logging.ERROR)
    use_links(links)
    keep_model = "keep_model" in inspect.getsource(core.Brain._cmd_baseline)
    saved = (F.baseline, core.BASELINE_MS)
    # The brain keeps every link of the layout (rates, baseline, windows); `links` is what the
    # model's feature vector is built from. Its "why" list assumes the two are the same, and
    # nothing here reads it.
    brain = core.Brain(clock=None, nodes=doc, links=[x["id"] for x in doc["links"]])
    brain._why_weights = lambda: {}
    clk = [msgs[0]["recv_t"]]
    brain._clock = lambda: clk[0]
    T0 = rf.T0_MS
    cmds = sorted(((T0 + t * 1000, c, a) for t, c, a in S.cmds), key=lambda c: c[0])
    tB = T0 + plan["tB"] * 1000
    log, events = [], []
    out = {"trained": False, "keep_model": keep_model, "desk_baseline_t": None, "blind_s": 0.0, "null_s": 0.0}
    li = {lk: i for i, lk in enumerate(doc["links"] and [x["id"] for x in doc["links"]])}

    watch_on_pred = brain.watch.on_pred

    def tap(t, pred):
        if t >= tB:
            if pred is None:
                log.append((t, None))
            else:
                w = brain.window["links"]
                std, drop = [0.0] * len(li), [0.0] * len(li)
                for lk, s in w.items():
                    if s["n"]:
                        std[li[lk]], drop[li[lk]] = s["std"], s["drop_db"] or 0.0
                log.append((t, (bool(pred["present"]), pred["kind"], pred["zone"] or 0, pred["motion"],
                                len(pred.get("zone_set") or []), std, drop)))
        return watch_on_pred(t, pred)
    brain.watch.on_pred = tap

    ci, meta_seq, pending = 0, 0, []
    next_tick = (msgs[0]["recv_t"] // 100 + 1) * 100

    def run_cmds(upto):
        nonlocal ci, meta_seq
        while ci < len(cmds) and cmds[ci][0] <= upto:
            tc, c, a = cmds[ci]
            ci += 1
            clk[0] = int(tc)
            if c == "baseline" and a.get("keep_model"):
                if not keep_model:
                    continue            # this brain can only baseline as "a new place": the model would be dropped
                if base_est == "mean":
                    F.baseline = mean_baseline
                elif base_est == "quiet":
                    F.baseline, core.BASELINE_MS = quiet_baseline, 60_000
                core.BASELINE_MS = max(core.BASELINE_MS, int(plan["scene"]["baseline_s"] * 1000)) \
                    if base_est != "quiet" else core.BASELINE_MS
            brain.on_cmd({"v": 2, "type": "cmd", "cmd": c, "args": a})
            if c == "record_start":
                meta_seq += 1
                pending.append({"v": 2, "type": "meta", "t": int(tc), "seq": meta_seq, "src": "sim",
                                "session": a["session"], "purpose": a["purpose"], "walker": a["walker"],
                                "recv_t": int(tc) + 3})
            if c == "train":
                out["trained"] = brain.model is not None

    def tick(t):
        clk[0] = t
        st = brain.state()
        for e in brain.pop_events():
            events.append((t, e["kind"], e["info"]))
            if e["kind"] == "baseline_done" and t >= tB and out["desk_baseline_t"] is None:
                out["desk_baseline_t"] = (t - tB) / 1000
        if t >= tB:
            out["blind_s"] += 0.1 * (st["health"]["status"] == "blind")
            out["null_s"] += 0.1 * (st["pred"] is None)

    try:
        for m in msgs:
            t = m["recv_t"]
            while pending and pending[0]["recv_t"] <= t:
                clk[0] = pending[0]["recv_t"]
                brain.on_message(pending.pop(0))
            while next_tick <= t:
                run_cmds(next_tick)
                tick(next_tick)
                next_tick += 100
            run_cmds(t)
            clk[0] = t
            brain.on_message(m)
    finally:
        F.baseline, core.BASELINE_MS = saved
    out.update(brain=brain, log=log, events=events)
    return out


# ---------------------------------------------------------------- the rules, replayed

def replay_armed(log, confirm_s=0.0, n=10, need=6):
    """The section 6 armed rule on a decision log, with a wait before it fires.

    A person "appears" as today (present with kind person for `need` of the last `n`
    decisions). confirm_s = 0 is today's rule: the intrusion is raised at once. With
    confirm_s > 0 it is raised only if they are still there that long after appearing;
    someone gone before that gives passed_by instead. Returns [(t_ms, kind, zone)].
    """
    recent, inside, seen_t, out = deque(maxlen=n), False, None, []
    for t, d in log:
        if d is None:
            recent.clear()
            continue
        person = d[0] and d[1] == "person"
        recent.append((person, d[2]))
        k = sum(1 for p, _ in recent if p)
        if not inside and k >= need:
            inside, seen_t = True, t
            if confirm_s <= 0:
                out.append((t, "intrusion", _mode([z for p, z in recent if p])))
                seen_t = None
        elif inside and len(recent) - k >= min(need, 6):
            inside = False
            if seen_t is not None:
                out.append((t, "passed_by", 0))
                seen_t = None
        if inside and seen_t is not None and t - seen_t >= confirm_s * 1000:
            out.append((t, "intrusion", _mode([z for p, z in recent if p]) if k else 0))
            seen_t = None
    return out


def _mode(v):
    return max(set(v), key=v.count) if v else 0


def replay_found(log, show_n=1, hold_s=3.0):
    """The arrival screen: "Found you." shows after show_n present decisions in a row and the
    room opens after hold_s of it without a break (#477: show_n 1, hold 3 s).
    Returns ([t_ms of each time the words appear], [t_ms the room opens])."""
    shown, opened, run, since, room = [], [], 0, None, False
    for t, d in log:
        person = d is not None and d[0] and d[1] == "person"
        run = run + 1 if person else 0
        if room:                         # the room is open; the next visitor starts again once this one is gone
            room = person
        elif run >= show_n:
            if since is None:
                since = t
                shown.append(t)
            elif t - since >= hold_s * 1000:
                opened.append(t)
                since, room = None, True
        else:
            since = None
    return shown, opened


def replay_still(log, limits, resets=(), run_n=5, source="forest", mode="reset", std_db=2.5, pause_reset_n=30,
                 links=None):
    """The section 6 still timer on a decision log. Returns [(t_ms, zone)] for each alert_on.

    run_n: moving decisions in a row before the timer resets (today 5).
    source "forest": moving is the model's pred.motion. "zone": moving when one of the occupied
      zone's own strip links has a 1 s std of at least std_db (people elsewhere don't count).
    mode "reset": as today. "pause": a moving decision stops the count without clearing it; it
      clears after pause_reset_n moving decisions in a row (real walking), a zone change or leaving.
    resets: times (ms) of reset / reset_alert commands.
    """
    recent = deque(maxlen=10)
    zone, kind, still, alerting, run, last = 0, "none", 0, False, 0, None
    out, resets, ri = [], sorted(resets), 0
    zl = {z: [links.index(k) for k in ks if k in links] for z, ks in ZONE_LINKS.items()} if links else {}
    for t, d in log:
        while ri < len(resets) and resets[ri] <= t:
            still, alerting, ri = 0, False, ri + 1
        dt = 0 if last is None else max(0, t - last)
        last = t
        if d is None:
            continue
        present, k, z, motion, _, std, _ = d
        raw_zone = z if present else 0
        recent.append((raw_zone, k or "none"))
        zs, ks = [a for a, _ in recent], [b for _, b in recent]
        need = min(6, len(zs) // 2 + 1)
        new_zone = next((v for v in set(zs) if zs.count(v) >= need), zone)
        kind = next((v for v in set(ks) if ks.count(v) >= need), kind)
        person = kind == "person"
        if source == "zone" and zl.get(new_zone):
            moving = k == "person" and max(std[i] for i in zl[new_zone]) >= std_db
        else:
            moving = k == "person" and motion == "moving"
        run = run + 1 if moving else 0
        if new_zone != zone:
            zone, still = new_zone, 0
        elif not person:
            still = 0
        elif mode == "reset":
            still = 0 if run >= run_n else still + dt
        else:
            if run >= pause_reset_n:
                still = 0
            elif run < run_n:
                still += dt
        limit = limits.get(zone) if person else None
        if not alerting and limit is not None and still >= limit * 1000:
            alerting = True
            out.append((t, zone))
    return out


# (wait after appearing in s, decisions looked at, how many of them must say "person")
ARMED_GRID = ([(c, 10, 6) for c in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0)]
              + [(0.0, 10, 8), (0.0, 10, 10), (0.0, 20, 16), (0.0, 30, 24), (1.0, 10, 8), (2.0, 10, 8), (1.0, 20, 16),
                 (2.0, 20, 16), (3.0, 20, 16)])
FOUND_GRID = [(1, 3.0), (3, 3.0), (5, 3.0), (10, 3.0), (15, 3.0), (20, 3.0), (5, 2.0), (10, 2.0), (10, 1.0)]
STILL_GRID = ([{"mode": "reset", "source": "forest", "run_n": n} for n in (5, 10, 15, 20, 30)]
              + [{"mode": "reset", "source": "zone", "run_n": 5, "std_db": s} for s in (2.0, 2.5, 3.0, 4.0)]
              + [{"mode": "reset", "source": "zone", "run_n": 10, "std_db": s} for s in (2.5, 3.0)]
              + [{"mode": "pause", "source": "forest", "run_n": 5, "pause_reset_n": n} for n in (15, 20, 30)]
              + [{"mode": "pause", "source": "zone", "run_n": 5, "std_db": 3.0, "pause_reset_n": 20}])


def _name(v: dict) -> str:
    return " ".join(f"{k}={v[k]}" for k in sorted(v))


# ---------------------------------------------------------------- scoring

def score(S: Scene, plan: dict, res: dict, radio: DeskRadio, links) -> dict:
    sec = lambda ms: (ms - rf.T0_MS) / 1000.0   # noqa: E731
    sp = S.spans
    log = res["log"]
    brain = res["brain"]
    m = {"trained": res["trained"], "keep_model": res["keep_model"], "desk_baseline_s": res["desk_baseline_t"],
         "blind_s": round(res["blind_s"], 1), "null_s": round(res["null_s"], 1),
         "live_s": round(plan["T"] - plan["tB"], 1), "decisions": sum(1 for _, d in log if d is not None)}
    if not res["trained"] or not m["decisions"]:
        return m
    if brain.base:
        err = [brain.base[lk] - radio.quiet_dbm(lk, desk=res["desk_baseline_t"] is not None)
               for lk in links if lk in brain.base]
        m["base_err_db"] = round(float(np.mean(np.abs(err))), 2)
        m["base_bias_db"] = round(float(np.mean(err)), 2)

    people = [b for b in S.bodies if b.tag in ("visit1", "visit1b", "visit2", "intruder")]
    occupied = sorted(s for b in people for s in b.strip_spans())
    special = {tag: sp[tag][0] for tag in ("through", "brush")}
    passers = [b for b in S.bodies if b.tag in ("passer", "passer_brush")]
    live0 = max(sp["desk_baseline"][0][1], plan["tB"] + (res["desk_baseline_t"] or 0.0)) + 1.0

    def busy(t0, t1, pad=0.0):
        return any(a - pad < t1 and t0 < b + pad for a, b in occupied)

    def near_special(t0, t1):
        return next((tag for tag, (a, b) in special.items() if a < t1 and t0 < b), None)

    alone = []          # passers who go by while nobody we scripted is in the strip
    for b in passers:
        ab = b.abeam_span()
        if ab and ab[0] > live0 and not busy(ab[0] - 1.0, ab[1] + 1.0) and not near_special(ab[0], ab[1]):
            alone.append(b)
    m["passers"] = len(passers)
    m["passers_alone"] = len(alone)
    m["passers_alone_in_strip"] = sum(1 for b in alone if b.lane >= 0)
    empty_s = (plan["T"] - live0) - sum(min(b, plan["T"]) - max(a, live0) for a, b in occupied if b > live0)
    m["empty_min"] = round(max(empty_s, 0.0) / 60, 2)

    def cause(t, back_s):
        """What a "somebody is there" at time t (s) answers to."""
        if busy(t - back_s, t, pad=0.3):
            return "person"
        tag = near_special(t - back_s, t + 0.3)
        if tag:
            return tag
        for b in passers:
            ab = b.abeam_span()
            if ab and ab[0] - 0.5 <= t and t - back_s <= ab[1] + 0.5:
                return "passer_in" if b.lane >= 0 else "passer_out"
        return "noise"

    # presence, zone and motion as the model saw the visit
    def frac(span, fn):
        v = [fn(d) for t, d in log if d is not None and span[0] + 1.0 <= sec(t) < span[1]]
        return round(float(np.mean(v)), 3) if v else None
    b1 = next(b for b in S.bodies if b.tag == "visit1")
    for st in ("short", "up", "left", "still"):
        if st in sp:
            a, c = sp[st][0]
            x, _ = b1.at((a + c) / 2)
            z = 1 + int(x >= SPLIT_X)
            m[f"present_{st}"] = frac((a, c), lambda d: d[0])
            m[f"zone_ok_{st}"] = frac((a, c), lambda d, z=z: d[0] and d[2] == z)
    m["moving_still"] = frac(sp["still"][0], lambda d: d[3] == "moving")
    m["moving_fidget"] = frac(sp["fidget"][0], lambda d: d[3] == "moving")
    m["present_empty"] = frac((live0, sp["visit1"][0][0]), lambda d: d[0])

    # the brain's own events (today's rules, armed only where the script armed it)
    ev = [(sec(t), k, i) for t, k, i in res["events"] if sec(t) >= plan["tB"]]
    ae = sp["armed_empty"][0]
    intr = [t for t, k, _ in ev if k == "intrusion"]
    m["today_armed_empty_intrusions"] = sum(1 for t in intr if ae[0] <= t < ae[1])
    m["today_armed_empty_passers"] = sum(1 for b in passers if b.abeam_span() and ae[0] <= b.abeam_span()[0] < ae[1] - 1)
    m["today_alerts"] = [round(t, 1) for t, k, _ in ev if k == "alert_on"]
    m["today_enters"] = sum(1 for t, k, _ in ev if k == "enter")

    # armed rule variants over everything after the desk baseline
    L = [(t, d) for t, d in log if sec(t) >= live0]
    ib = next(b for b in S.bodies if b.tag == "intruder")
    i_in = ib.strip_spans()[0] if ib.strip_spans() else sp["intruder"][0]
    armed = {}
    for c, n_dec, need in ARMED_GRID:
        evs = replay_armed(L, confirm_s=c, n=n_dec, need=need)
        r = {"false_in": 0, "false_out": 0, "noise": 0, "passed_by": 0, "through": None, "brush": None,
             "intruder": False, "intruder_s": None, "visit1": False, "visit1_while_back": False}
        for t, k, _ in evs:
            ts = sec(t)
            why = cause(ts, c + n_dec / 10 + 1.0)
            if k == "passed_by":
                r["passed_by"] += why in ("passer_in", "passer_out", "noise")
                if why in special and r[why] is None:
                    r[why] = "passed_by"
                continue
            if why == "passer_in":
                r["false_in"] += 1
            elif why == "passer_out":
                r["false_out"] += 1
            elif why == "noise":
                r["noise"] += 1
            elif why in special:
                r[why] = "intrusion"
            elif i_in[0] <= ts <= i_in[1] + 1.5:
                if not r["intruder"]:
                    r["intruder"], r["intruder_s"] = True, round(ts - i_in[0], 2)
            elif sp["visit1"][0][0] <= ts <= sp["visit1"][0][1]:
                r["visit1"] = True
                r["visit1_while_back"] = r["visit1_while_back"] or ts < sp["short"][0][1]
        armed[f"{c}/{n_dec}/{need}"] = r
    m["armed"] = armed

    # the arrival screen
    found = {}
    v1 = sp["visit1"][0]
    for show_n, hold_s in FOUND_GRID:
        shown, opened = replay_found(L, show_n, hold_s)
        r = {"false_shown": 0, "false_opened": 0, "found_s": None, "found_from_up_s": None, "open_s": None}
        for t in shown:
            ts = sec(t)
            if cause(ts, show_n / 10 + 1.5) not in ("person",):
                r["false_shown"] += 1
            elif r["found_s"] is None and v1[0] <= ts <= v1[1]:
                r["found_s"] = round(ts - sp["short"][0][0], 2)
                r["found_from_up_s"] = round(ts - sp["up"][0][0], 2)
        for t in opened:
            ts = sec(t)
            if cause(ts, hold_s + show_n / 10 + 1.5) != "person":
                r["false_opened"] += 1
            elif r["open_s"] is None and v1[0] <= ts <= v1[1]:
                r["open_s"] = round(ts - sp["short"][0][0], 2)
        found[f"{show_n}/{hold_s}"] = r
    m["found"] = found

    # the still timer
    limits = {z["id"]: z.get("still_alert_s") for z in brain.nodes["zones"]}
    resets = [rf.T0_MS + t * 1000 for t, c, _ in S.cmds if c in ("reset", "reset_alert")]
    s0, s1 = sp["still"][0]
    f0, f1 = sp["fidget"][0]
    all_links = [x["id"] for x in brain.nodes["links"]]
    still = {}
    for v in STILL_GRID:
        al = [sec(t) for t, _ in replay_still(L, limits, resets, links=all_links, **v)]
        hit = [t for t in al if s0 + 8.0 <= t <= s1 + 1.0]
        still[_name(v)] = {
            "hit": bool(hit), "late_s": round(hit[0] - s0 - 10.0, 2) if hit else None,
            "early": any(v1[0] <= t < s0 + 8.0 for t in al),
            "fidget": any(sp["visit2"][0][0] <= t <= f1 + 1.0 for t in al),
            "other": sum(1 for t in al if not (v1[0] <= t <= s1 + 1.0) and not (sp["visit2"][0][0] <= t <= f1 + 1.0)),
        }
    m["still"] = still
    m["still_passers"] = sum(1 for b in passers if b.abeam_span() and b.abeam_span()[0] < s0 + 10 and b.abeam_span()[1] > s0)
    return m


# ---------------------------------------------------------------- one session

def session(seed=0, env=None, scene=None, links="twelve", base_est="median", keep_log=False):
    """Build, simulate, run and score one desk session. Returns a JSON-ready dict."""
    env = env or rf.Env()
    t0 = time.perf_counter()
    _, core, _, _ = _brain_modules()
    if "keep_model" not in inspect.getsource(core.Brain._cmd_baseline):
        # This brain drops its model on any baseline taken by hand, so the session stays in
        # tonight's place: no new baseline and no shift in the links' levels (the kind case).
        scene = dict(scene or {}, place_db=0.0)
    if base_est == "quiet":
        scene = dict(scene or {}, baseline_s=60)
    S, plan = build(seed, env, scene)
    doc = desk_doc(plan["scene"]["reach_m"])
    lay = Lay(doc)
    msgs, radio = messages(S, lay, plan, seed)
    t1 = time.perf_counter()
    names = link_set(links, doc)
    res = drive(msgs, S, plan, doc, names, base_est)
    metrics = score(S, plan, res, radio, names)
    t2 = time.perf_counter()
    out = {"seed": seed, "env": env.to_dict(), "scene": plan["scene"], "links": links, "base_est": base_est,
           "layout": LAYOUT_PIN, "metrics": metrics,
           "timing": {"simulate_s": round(t1 - t0, 2), "brain_s": round(t2 - t1, 2), "messages": len(msgs),
                      "sim_minutes": round(plan["T"] / 60, 2)}}
    if keep_log:
        out["_log"], out["_events"], out["_scene"], out["_brain"] = res["log"], res["events"], S, res["brain"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="One simulated desk session through the real brain (SIMULATED).")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rate", type=float, default=6.0, help="people walking past per minute")
    ap.add_argument("--links", default="twelve", choices=["twelve", "six", "cross", "cross+ends"])
    ap.add_argument("--visit", default="standard", choices=VISITS)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = session(seed=args.seed, scene={"rate": args.rate, "visit": args.visit}, links=args.links)
    if args.json:
        print(json.dumps(out, default=float))
        return
    print("SIMULATED desk session, seed", args.seed)
    for k, v in out["metrics"].items():
        print(f"  {k}: {v}")
    print("  timing:", out["timing"])


if __name__ == "__main__":
    main()
