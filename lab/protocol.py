"""The scripted deployment one lab session plays out. SIMULATED, dev only.

build() writes a Script (lab/rf.py) for one deployment, start to finish:
  1. baseline (20 s, empty square, label_mode off);
  2. training recordings: walkers standing on the marked spots (zone centres,
     which sit on the diagonal links) and wandering, an empty room, two tray
     placements in label_mode object, then the train command;
  3. held-out walkers, never in training;
  4. the live demo with the camera unplugged (docs/demo-runbook.md): zone tour,
     free walking, a still stand in zone 4 and a wave, a long still stand, an
     empty room, the tray near the router, a person beside the tray, a 6 s
     beacon outage and a 1.5 s one, and an empty room again.
It returns the script and a plan: the commands with their times, the spans of
each part, and the ground truth the scoring needs.
"""
from __future__ import annotations

import numpy as np

from lab import rf
from sim.fake import ROUTER_SPOTS as SPOTS

ZONE_XY = {1: (0.5, 1.5), 2: (1.5, 1.5), 3: (0.5, 0.5), 4: (1.5, 0.5)}


def _rand_point(rng, zone=None, margin=0.15):
    if zone is None:
        return rng.uniform(margin, 2 - margin), rng.uniform(margin, 2 - margin)
    cx, cy = ZONE_XY[zone]
    return cx + rng.uniform(-0.5 + margin, 0.5 - margin), cy + rng.uniform(-0.5 + margin, 0.5 - margin)


def _spot(rng, zone, jitter):
    """A marked spot: the zone centre (it sits on that zone's diagonal link), give or take."""
    cx, cy = ZONE_XY[zone]
    return cx + rng.uniform(-jitter, jitter), cy + rng.uniform(-jitter, jitter)


def _tour(sc, rng, proto, wander=4):
    """Stand on each marked spot, then wander the square with short pauses."""
    for z in rng.permutation([1, 2, 3, 4]):
        sc.walk_to(*_spot(rng, int(z), proto["spot_jitter_m"]))
        sc.stand(proto["train_still_s"] * rng.uniform(0.8, 1.2))
    for _ in range(wander):
        sc.walk_to(*_rand_point(rng))
        sc.stand(rng.uniform(0.0, 1.5))


PROTOCOL = {
    "train_walkers": 3,
    "train_still_s": 5.0,     # how long each walker stands on each marked spot while recording
    "spot_jitter_m": 0.12,    # how far from the zone centre people actually stand
    "tray_jitter_m": 0.05,    # how far from T1 the tray ends up in the live demo
    "wave_dist_m": 0.5,       # the waver's distance from the router-receiver line
    "object_s": 15.0,         # how long each tray placement is recorded for training
}


def build(seed: int, env: rf.Env, live_person: dict = None, wave: dict = None, smoke=False, proto=None):
    """The session's Script and its plan (commands, spans, ground truth)."""
    proto = dict(PROTOCOL, **(proto or {}))
    rng = np.random.default_rng(seed)
    sc = rf.Script(rng, env)
    cmds, spans = [], {}
    walkers = [rf.Person.draw(rng) for _ in range(2 if smoke else int(proto["train_walkers"]))]
    held = [rf.Person.draw(rng, **(live_person or {})) for _ in range(1 if smoke else 2)]

    def cmd(c, **args):
        cmds.append((sc.t, c, args))

    def span(tag, t0):
        spans.setdefault(tag, []).append((t0, sc.t))

    sc.idle(1.0)
    cmd("baseline")
    sc.idle(24.0)
    for k, w in enumerate(walkers):
        cmd("record_start", session=f"t{k}", purpose="train", walker=f"w{k}")
        cmd("label_mode", mode="person")
        sc.label_mode = "person"
        sc.idle(1.0)
        sc.enter(w)
        _tour(sc, rng, proto, wander=2 if smoke else 5)
        sc.leave()
        sc.idle(1.5)
        cmd("record_stop")
    cmd("record_start", session="e0", purpose="train", walker=None)
    sc.idle(10.0)
    cmd("record_stop")
    cmd("record_start", session="o0", purpose="object", walker=None)
    cmd("label_mode", mode="object")
    sc.label_mode = "object"
    helper = walkers[0]
    tray_db = rng.uniform(6, 15)   # one metal tray for the whole session
    for spot in ([(1.0, 0.2)] if smoke else [(1.0, 0.2), _rand_point(rng)]):
        sc.enter(helper)
        sc.walk_to(spot[0] + 0.3, spot[1])
        sc.stand(1.5)
        sc.place(*spot, width_m=0.3, depth_db=tray_db)
        sc.leave()
        sc.idle(proto["object_s"])
        sc.enter(helper)
        sc.walk_to(spot[0] + 0.3, spot[1])
        sc.stand(1.0)
        sc.remove_objects()
        sc.leave()
        sc.idle(2.0)
    cmd("record_stop")
    cmd("label_mode", mode="off")
    sc.label_mode = "off"
    cmd("train")
    sc.idle(2.0)
    for k, w in enumerate(held):          # held-out walkers: never in training
        t0 = sc.t
        sc.enter(w)
        _tour(sc, rng, proto, wander=3 if smoke else 6)
        sc.leave()
        span("heldout", t0)
        sc.idle(1.0)

    # ---- live demo, camera unplugged (docs/demo-runbook.md)
    sc.camera = "off"
    sc.idle(2.0)
    live0 = sc.t
    person = held[0]
    t0 = sc.t
    sc.enter(person)
    for z in (3, 4, 2, 1):
        sc.walk_to(*_spot(rng, z, proto["spot_jitter_m"]))
        sc.stand(rng.uniform(3, 5))
    span("tour", t0)
    t0 = sc.t
    while sc.t - t0 < (15 if smoke else 35):
        sc.walk_to(*_rand_point(rng))
        sc.stand(rng.uniform(0.0, 1.0))
    span("walk", t0)
    # no-movement alert in zone 4, then the wave
    wave = dict({"hz": rng.uniform(1.6, 2.4), "dist_m": proto["wave_dist_m"], "s": rng.uniform(2.5, 4.0)},
                **(wave or {}))
    j = proto["spot_jitter_m"]   # the zone 4 spot slides along its diagonal to set the distance
    sc.walk_to(1.0 + wave["dist_m"] + rng.uniform(-j, j) / 2, wave["dist_m"] + rng.uniform(-j, j) / 2)
    t0 = sc.t
    sc.stand(13.0)
    span("alert4", t0)
    t0 = sc.t
    sc.wave(wave["s"], hz=wave["hz"])
    span("wave", t0)
    t0 = sc.t
    sc.stand(2.0)
    span("after_wave", t0)
    zone = int(rng.choice([1, 2, 3]))
    sc.walk_to(*_spot(rng, zone, proto["spot_jitter_m"]))
    t0 = sc.t
    sc.stand(10.0 if smoke else 25.0)
    span("still", t0)
    sc.leave()
    t0 = sc.t
    sc.idle(10.0)
    span("empty", t0)
    # the tray near the router
    tj = proto["tray_jitter_m"]
    tray = (1.0 + rng.uniform(-tj, tj), 0.2 + rng.uniform(-tj, tj))
    sc.enter(walkers[0])
    sc.walk_to(tray[0] + 0.35, tray[1] + 0.2)
    sc.stand(1.0)
    sc.place(*tray, width_m=0.3, depth_db=tray_db)
    t_tray = sc.t
    sc.leave()
    t0 = sc.t
    sc.idle(10.0 if smoke else 18.0)
    span("tray_empty", t0)
    sc.enter(person)
    sc.walk_to(*_spot(rng, int(rng.choice([2, 3])), proto["spot_jitter_m"]))
    t0 = sc.t
    sc.stand(10.0 if smoke else 15.0)
    span("tray_still", t0)
    sc.leave()
    sc.enter(walkers[0])
    sc.walk_to(tray[0] + 0.35, tray[1] + 0.2)
    sc.stand(1.0)
    sc.remove_objects()
    sc.leave()
    t0 = sc.t
    sc.idle(8.0)
    span("empty", t0)
    # beacon outages while someone walks
    sc.enter(person)
    t0 = sc.t
    sc.walk_to(*_rand_point(rng))
    sc.outage(6.0, node="east")
    out_long = (sc.t, sc.t + 6.0)
    while sc.t - out_long[0] < 10.0:
        sc.walk_to(*_rand_point(rng))
        sc.stand(rng.uniform(0.0, 1.0))
    sc.outage(1.5, link="west>unoq:ble")
    out_short = (sc.t, sc.t + 1.5)
    while sc.t - out_short[0] < 8.0:
        sc.walk_to(*_rand_point(rng))
    span("outage", t0)
    sc.leave()
    t0 = sc.t
    sc.idle(10.0 if smoke else 15.0)
    span("empty", t0)
    plan = {"cmds": cmds, "spans": spans, "live0": live0, "live1": sc.t, "wave": wave,
            "tray": tray, "t_tray": t_tray, "out_long": out_long, "out_short": out_short,
            "walkers": [vars(w) for w in walkers], "held": [vars(h) for h in held],
            "best_spots": best_spots(tray), "proto": proto}
    return sc, plan


def best_spots(tray, width=0.3, depth=10.0, tol_db=0.5):
    """Router spots (not S-home) whose new Wi-Fi link the tray blocks least (ties within tol_db)."""
    unoq = rf.NODES["unoq"]
    loss = {s: float(rf.shadow_db(np.array([tray[0]]), np.array([tray[1]]), xy, unoq,
                                  rf.LAMBDA_M["wifi"], width, depth)[0])
            for s, xy in SPOTS.items() if s != "S-home"}
    lo = min(loss.values())
    return sorted(s for s, v in loss.items() if v - lo <= tol_db)


