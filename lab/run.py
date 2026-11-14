"""Whole simulated sessions through the real brain and advisor. SIMULATED, dev only.

    python -m lab.run --smoke            # one short session, prints its metrics
    python -m lab.run --seed 3 --json    # one full session as JSON

One session is one deployment, start to finish, on one continuous radio
timeline from lab/rf.py:
  1. baseline (20 s, empty square, label_mode off);
  2. training recordings: three walkers, an empty room, two tray placements
     (label_mode object), then the train command;
  3. two held-out walkers, scored in batch against the true zone;
  4. the live demo with the camera unplugged: zone tour, free walking, a still
     stand in zone 4 (no-movement alert) and a wave (check-in), a long still
     stand elsewhere, an empty room, the tray near the router (object, advice),
     a person beside the tray, a 6 s beacon outage and a 1.5 s one, empty again.
Everything runs through brain.core.Brain, brain.alert.Watch and
advisor.advise. Brain knobs come from `cfg` and are set on the modules for
the run only. Cheap replays then re-run the check-in, health and X-ray rules
on the same recorded live stream with other thresholds.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import time
from pathlib import Path

import numpy as np

from lab import overlay, rf

SOURCES = overlay.install()
from advisor.advise import advise            # noqa: E402
from brain import alert as AL                 # noqa: E402
from brain import core                        # noqa: E402
from brain import features as F               # noqa: E402
from brain import health as H                 # noqa: E402
from brain import train as TR                 # noqa: E402
from brain import xray as X                   # noqa: E402

NODES_DOC = json.loads((overlay.ROOT / "radio" / "nodes.json").read_text(encoding="utf-8"))
LIMITS = {z["id"]: z.get("still_alert_s") for z in NODES_DOC["zones"]}
SPOTS = {s["id"]: tuple(s["xyz_m"][:2]) for s in NODES_DOC["router_spots"]}
ZONE_XY = {1: (0.5, 1.5), 2: (1.5, 1.5), 3: (0.5, 0.5), 4: (1.5, 0.5)}

DEFAULT_CFG = {
    "n_estimators": TR.FOREST["n_estimators"], "max_depth": TR.FOREST["max_depth"],
    "window_ms": F.WINDOW_MS,
    "cross_db": AL.CROSS_DB, "crossings": AL.CROSSINGS, "cross_window_ms": AL.CROSS_WINDOW_MS,
    "smooth_n": AL.SMOOTH_N, "other_link_db": AL.OTHER_LINK_DB,
    "stale_frac": H.STALE_FRAC, "jump_db": H.JUMP_DB, "blind_after_s": H.BLIND_AFTER_S,
    "clear_after_s": H.CLEAR_AFTER_S,
    "alpha_rel": X.ALPHA_REL, "static_std_db": X.STATIC_STD_DB,
}
_TARGETS = {
    "window_ms": (F, "WINDOW_MS"), "cross_db": (AL, "CROSS_DB"), "crossings": (AL, "CROSSINGS"),
    "cross_window_ms": (AL, "CROSS_WINDOW_MS"), "smooth_n": (AL, "SMOOTH_N"),
    "other_link_db": (AL, "OTHER_LINK_DB"),
    "stale_frac": (H, "STALE_FRAC"), "jump_db": (H, "JUMP_DB"), "blind_after_s": (H, "BLIND_AFTER_S"),
    "clear_after_s": (H, "CLEAR_AFTER_S"), "alpha_rel": (X, "ALPHA_REL"),
    "static_std_db": (X, "STATIC_STD_DB"),
}
_steady_level = X.steady_level


def _steady_now(t, v, now, span_s=None, std_db=None):
    """xray.steady_level binds its threshold at import; this reads the live constant."""
    return _steady_level(t, v, now, X.STATIC_S if span_s is None else span_s,
                         X.STATIC_STD_DB if std_db is None else std_db)


X.steady_level = _steady_now


@contextlib.contextmanager
def patched(cfg: dict):
    """Set brain constants from cfg for the duration of a run, then put them back."""
    saved = {k: getattr(*_TARGETS[k]) for k in _TARGETS}
    forest = dict(TR.FOREST)
    try:
        for k, v in cfg.items():
            if k in _TARGETS:
                setattr(*_TARGETS[k], v)
        TR.FOREST.update(n_estimators=int(cfg.get("n_estimators", forest["n_estimators"])),
                         max_depth=cfg.get("max_depth", forest["max_depth"]))
        yield
    finally:
        for k, v in saved.items():
            setattr(*_TARGETS[k], v)
        TR.FOREST.clear()
        TR.FOREST.update(forest)


# ---------------------------------------------------------------- the protocol

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


def best_spots(tray, width=0.3, depth=10.0):
    """Router spots (not S-home) whose new Wi-Fi link the tray blocks least (ties within 0.5 dB)."""
    unoq = rf.NODES["unoq"]
    loss = {s: float(rf.shadow_db(np.array([tray[0]]), np.array([tray[1]]), xy, unoq,
                                  rf.LAMBDA_M["wifi"], width, depth)[0])
            for s, xy in SPOTS.items() if s != "S-home"}
    lo = min(loss.values())
    return sorted(s for s, v in loss.items() if v - lo <= 0.5)


# ---------------------------------------------------------------- running it

class _CachedForest:
    """A fitted forest whose predict_proba answers from a batch run when it can."""

    def __init__(self, forest, X):
        self.forest, self.classes_ = forest, forest.classes_
        self.cache = {}
        if len(X):
            for row, p in zip(X, forest.predict_proba(X)):
                self.cache[row.tobytes()] = p

    def predict_proba(self, x):
        if len(x) != 1:
            return self.forest.predict_proba(x)
        p = self.cache.get(np.ascontiguousarray(x[0], dtype=float).tobytes())
        return self.forest.predict_proba(x) if p is None else p[None, :]

    def predict(self, x):
        return self.classes_.take(np.argmax(self.predict_proba(x), axis=1))


def _speed_up(model, msgs, base):
    """Batch every live window through the forests once (same features as Brain's windower)."""
    rows = [F.vector(w) for w in F.windows(msgs, base)]
    Xl = np.asarray(rows, dtype=float).reshape(-1, len(F.feature_names()))
    for name in ("zone", "kind", "motion"):
        forest = getattr(model, name)
        if forest is not None:
            setattr(model, name, _CachedForest(forest, Xl))


def drive(msgs, plan):
    """Feed one session through Brain + Watch + advise. Returns the tick log and objects."""
    brain = core.Brain(clock=None, nodes=NODES_DOC)
    clk = [msgs[0]["recv_t"]]
    brain._clock = lambda: clk[0]
    watch = AL.Watch(limits=LIMITS)
    T0 = rf.T0_MS
    cmds = sorted(((T0 + t * 1000, c, a) for t, c, a in plan["cmds"]), key=lambda c: c[0])
    meta_seq = [0]
    ticks, events, advice = [], [], []
    live_rssi = []
    out = {"train_s": None, "trained": False, "baseline_t": None, "baseline_restarts": 0}
    ci = 0
    next_tick = (msgs[0]["recv_t"] // 100 + 1) * 100
    live0 = T0 + plan["live0"] * 1000
    pending = []

    def run_cmds(upto):
        nonlocal ci
        while ci < len(cmds) and cmds[ci][0] <= upto:
            tc, c, a = cmds[ci]
            ci += 1
            clk[0] = int(tc)
            brain.on_cmd({"v": 2, "type": "cmd", "cmd": c, "args": a})
            if c == "baseline":
                out["baseline_cmd"] = tc
            if c == "record_start":
                meta_seq[0] += 1
                pending.append({"v": 2, "type": "meta", "t": int(tc), "seq": meta_seq[0], "src": "sim",
                                "session": a["session"], "purpose": a["purpose"], "walker": a["walker"],
                                "recv_t": int(tc) + 3})
            if c == "train" and brain.model is not None:
                out["trained"] = True
                out["train_s"] = brain.model.train_s
                _speed_up(brain.model, [m for m in msgs if m["recv_t"] >= tc - 2500], brain.base)

    def tick(t):
        clk[0] = t
        st = brain.state()
        evs = brain.pop_events()
        watch.on_pred(t, brain.pred)
        for k, info in watch.pop_events():
            events.append((t, k, info))
        for e in evs:
            events.append((t, e["kind"], e["info"]))
            if e["kind"] == "baseline_done" and out["baseline_t"] is None:
                out["baseline_t"] = t
        if t < live0:
            return
        p = brain.pred
        adv = advise(st["xray"], st["links"], NODES_DOC, st["objects"]) if st["objects"] else None
        if adv:
            advice.append((t, adv["to_spot"], adv["xy_m"]))
        ticks.append((t, None if p is None else (p["zone"] or 0), None if p is None else p["kind"],
                      None if p is None else p["motion"], brain.raw_kind, st["health"]["status"],
                      len(st["objects"]), [o["xy_m"] for o in st["objects"]], watch.alert_block()["state"]))

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
        if m["type"] == "label" and brain.capture and (m.get("persons_in_frame") or 0) > 0:
            out["baseline_restarts"] += 1
        brain.on_message(m)
        if m["type"] == "rssi":
            watch.on_rssi(m)
            if t >= live0:
                live_rssi.append(m)
    out.update(brain=brain, ticks=ticks, events=events, advice=advice, live_rssi=live_rssi)
    return out


# ---------------------------------------------------------------- scoring

def _in(t, spans):
    return any(a <= t < b for a, b in spans)


def score(tl, plan, res, msgs):
    T0 = rf.T0_MS
    sec = lambda ms: (ms - T0) / 1000.0   # noqa: E731
    m = {"trained": res["trained"], "train_s": res["train_s"],
         "baseline_s": None if res["baseline_t"] is None else round(sec(res["baseline_t"]) - 1.0, 1),
         "baseline_restarts": res["baseline_restarts"]}
    brain = res["brain"]
    if not res["trained"]:
        return m
    sp = plan["spans"]

    # held-out walkers, batch, against the true zone and the camera's label
    model = brain.model
    hw = [w for w in F.windows([x for x in msgs if _in(sec(x["recv_t"]), sp["heldout"])], brain.base)]
    if hw:
        Xh = np.asarray([F.vector(w) for w in hw], float)
        mid = np.array([sec(w["end"]) - F.WINDOW_MS / 2000 for w in hw])
        _, ztrue, _ = tl.truth(mid)
        zpred = model.zone.predict(Xh).astype(int)
        cam = np.array([(w["label"] or {}).get("zone", -1) if w["label"] else -1 for w in hw])
        m["heldout_acc"] = float(np.mean(zpred == ztrue))
        m["heldout_acc_cam"] = float(np.mean(zpred[cam >= 0] == cam[cam >= 0])) if (cam >= 0).any() else None
        m["heldout_presence_acc"] = float(np.mean((zpred > 0) == (ztrue > 0)))
        occ = ztrue > 0
        m["heldout_acc_occupied"] = float(np.mean(zpred[occ] == ztrue[occ])) if occ.any() else None
        m["heldout_windows"] = int(len(hw))
        ix = tl.idx(mid)
        dl = np.min([rf.geometry(tl.x[ix], tl.y[ix], rf.NODES[a], rf.NODES[b])[1]
                     for a, b in {rf.ENDS[k] for k in rf.LINKS}], axis=0)
        for name, lo, hi in (("near", 0, 0.15), ("mid", 0.15, 0.3), ("far", 0.3, 9)):
            sel = occ & (dl >= lo) & (dl < hi)
            m[f"heldout_acc_{name}"] = float(np.mean(zpred[sel] == ztrue[sel])) if sel.sum() >= 5 else None

    tk = res["ticks"]
    t = np.array([sec(x[0]) for x in tk])
    zone = np.array([-1 if x[1] is None else x[1] for x in tk])
    kind = np.array([x[2] or "null" for x in tk])
    nobj = np.array([x[6] for x in tk])
    status = np.array([x[5] for x in tk])
    inside, ztrue, moving = tl.truth(t - F.WINDOW_MS / 2000)
    has = zone >= 0
    m["pred_null_frac"] = float(np.mean(~has))
    person_spans = [s for k in ("tour", "walk", "alert4", "wave", "after_wave", "still", "tray_still", "outage")
                    for s in sp.get(k, [])]
    sel = has & np.array([_in(x, person_spans) for x in t])
    m["live_zone_acc"] = float(np.mean(zone[sel] == ztrue[sel])) if sel.any() else None
    empty_sel = has & np.array([_in(x, sp.get("empty", []) + sp.get("tray_empty", [])) for x in t])
    m["live_empty_acc"] = float(np.mean(zone[empty_sel] == 0)) if empty_sel.any() else None

    # person vs object
    tray_e = has & np.array([_in(x, [(a + 3, b) for a, b in sp["tray_empty"]]) for x in t])
    m["object_kind_frac"] = float(np.mean(kind[tray_e] == "object")) if tray_e.any() else None
    m["person_as_object_frac"] = float(np.mean(kind[sel] == "object")) if sel.any() else None
    m["tray_as_person_frac"] = float(np.mean(kind[tray_e] == "person")) if tray_e.any() else None

    ev = res["events"]
    live0, live1 = plan["live0"], plan["live1"]
    lev = [(sec(a), k, i) for a, k, i in ev if sec(a) >= live0]
    minutes_person = sum(b - a for a, b in person_spans) / 60
    # check-in
    w0, w1 = sp["wave"][0]
    chk = [a for a, k, _ in lev if k == "checkin"]
    hit = [a for a in chk if w0 <= a <= w1 + 2.0]
    m["checkin_hit"] = bool(hit)
    m["checkin_latency_s"] = round(hit[0] - w0, 2) if hit else None
    false_chk = [a for a in chk if not (w0 <= a <= w1 + 2.0)]
    m["false_checkins"] = len(false_chk)
    m["false_checkins_per_min"] = len(false_chk) / max(minutes_person, 1e-6)
    m["wave_dist_m"], m["wave_hz"], m["wave_s"] = plan["wave"]["dist_m"], plan["wave"]["hz"], plan["wave"]["s"]
    # no-movement alert in zone 4 (limit 10 s)
    a0, a1 = sp["alert4"][0]
    al = [a for a, k, _ in lev if k == "alert_on"]
    good = [a for a in al if a0 + 8.0 <= a <= w1 + 0.5]
    m["alert_hit"] = bool(good)
    m["alert_latency_s"] = round(good[0] - a0, 2) if good else None
    m["false_alerts"] = len([a for a in al if a not in good])
    m["alert_cleared_by_wave"] = any(k == "alert_off" and w0 <= a <= w1 + 2.0 for a, k, _ in lev)
    # SENSOR BLIND
    lo0, lo1 = plan["out_long"]
    bon = [a for a, k, _ in lev if k == "blind_on"]
    blind_now = np.array([x[5] == "blind" for x in tk])
    m["blind_hit"] = bool(np.any(blind_now & (t >= lo0) & (t <= lo1 + 1.0)))
    hits = [a for a in bon if lo0 <= a <= lo1 + 1.0]
    m["blind_latency_s"] = round(hits[0] - lo0, 2) if hits else None
    so0, so1 = plan["out_short"]
    m["blind_on_short_outage"] = any(so0 <= a <= so1 + 3.5 for a in bon)
    m["false_blinds"] = len([a for a in bon if not (lo0 <= a <= lo1 + 1.0) and not (so0 <= a <= so1 + 3.5)])
    m["blind_events"] = len(bon)
    blind_t = status == "blind"
    outside = ~np.array([lo0 <= x <= lo1 + 4.5 for x in t])
    m["blind_false_s"] = float(np.sum(blind_t & outside) * 0.1)
    m["false_blind_jump"] = len([1 for a, k, i in lev if k == "blind_on" and i.get("reason") == "jump"])
    # X-ray objects
    tray_on = np.array([plan["t_tray"] <= x < sp["tray_still"][0][1] + 1.0 for x in t])
    m["object_fp_s"] = float(np.sum((nobj > 0) & ~tray_on) * 0.1)
    still_spans = sp["alert4"] + sp["still"]
    m["still_person_became_object"] = bool(np.any((nobj > 0) & np.array([_in(x, still_spans) for x in t])))
    ts0, ts1 = sp["tray_still"][0]
    in_ts = np.array([ts0 <= x < ts1 for x in t])
    m["extra_object_with_person"] = bool(np.any(nobj[in_ts] > 1)) if in_ts.any() else None
    te0, te1 = sp["tray_empty"][0]
    det = [x for x, n in zip(t, nobj) if te0 <= x < te1 and n > 0]
    m["object_detected"] = bool(det)
    m["object_detect_s"] = round(det[0] - plan["t_tray"], 1) if det else None
    last = [x[7] for x in tk if te0 <= sec(x[0]) < te1 and x[7]]
    if last:
        d = min(math.dist(xy, plan["tray"]) for xy in last[-1])
        m["object_loc_err_m"] = round(d, 3)
    # advice
    adv = [(sec(a), s, xy) for a, s, xy in res["advice"]]
    adv_tray = [a for a in adv if plan["t_tray"] <= a[0] < ts1 + 1.0]
    m["advice_fired"] = bool(adv_tray)
    m["advice_right"] = (adv_tray[0][1] in plan["best_spots"]) if adv_tray else None
    m["advice_without_tray"] = len([a for a in adv if not (plan["t_tray"] <= a[0] < ts1 + 2.0)])
    m["tray_xy"] = [round(v, 3) for v in plan["tray"]]
    m["best_spots"] = plan["best_spots"]
    return m


# ---------------------------------------------------------------- replays

CHECKIN_GRID = [{"cross_db": c, "crossings": n, "cross_window_ms": w, "other_link_db": o}
                for c in (1.0, 1.5, 2.0, 3.0) for n in (3, 4, 6) for w in (1500, 2500, 3500)
                for o in (3.0, 6.0, 99.0)]
HEALTH_GRID = [{"stale_frac": s, "blind_after_s": b, "jump_db": j}
               for s in (0.3, 0.4, 0.5) for b in (2.0, 3.0, 4.0) for j in (4.0, 6.0, 8.0, 10.0)]
XRAY_GRID = [{"alpha_rel": a, "static_std_db": s} for a in (0.03, 0.1, 0.3, 1.0) for s in (0.8, 1.5, 2.5, 4.0)]
ALERT_HYST = (1, 3, 5, 10)   # reset the still timer only after this many "moving" decisions in a row


def replay_checkin(res, plan, grid=CHECKIN_GRID):
    """Re-run Watch (check-in and alert) on the same live readings and predictions."""
    T0 = rf.T0_MS
    preds = [(x[0], None if x[1] is None else {"present": x[1] > 0, "zone": x[1] or None,
                                               "kind": x[2], "motion": x[3]}) for x in res["ticks"]]
    w0, w1 = plan["spans"]["wave"][0]
    person_min = sum(b - a for k in ("tour", "walk", "alert4", "wave", "after_wave", "still", "tray_still",
                                     "outage") for a, b in plan["spans"].get(k, [])) / 60
    rows = []
    for g in grid:
        with patched(g):
            watch = AL.Watch(limits=LIMITS)
            chk, gated, i, recent = [], [], 0, []
            rs = res["live_rssi"]
            for t, p in preds:
                while i < len(rs) and rs[i]["recv_t"] <= t:
                    watch.on_rssi(rs[i])
                    i += 1
                watch.on_pred(t, p)
                recent = (recent + [p is not None and p["motion"] == "still"])[-10:]
                for k, _ in watch.pop_events():
                    if k == "checkin":
                        chk.append((t - T0) / 1000)
                        if sum(recent) >= 7:   # variant: only while the person reads still
                            gated.append((t - T0) / 1000)
        hit = [a for a in chk if w0 <= a <= w1 + 2.0]
        ghit = [a for a in gated if w0 <= a <= w1 + 2.0]
        rows.append(dict(g, hit=bool(hit), false=len(chk) - len(hit),
                         false_per_min=(len(chk) - len(hit)) / max(person_min, 1e-6),
                         latency_s=round(hit[0] - w0, 2) if hit else None,
                         hit_still=bool(ghit), false_per_min_still=(len(gated) - len(ghit)) / max(person_min, 1e-6)))
    return rows


def replay_health(res, plan, grid=HEALTH_GRID):
    """Re-run link health on the same live readings with the same classifier kinds."""
    T0 = rf.T0_MS
    brain = res["brain"]
    lo0, lo1 = plan["out_long"]
    so0, so1 = plan["out_short"]
    rows = []
    for g in grid:
        with patched(g):
            hm = H.Health.from_nodes(NODES_DOC)
            hm.set_base(brain.base)
            hm.set_expected(brain.expected_hz)
            on, i, rs, during = [], 0, res["live_rssi"], False
            for x in res["ticks"]:
                t = x[0]
                while i < len(rs) and rs[i]["recv_t"] <= t:
                    hm.add(rs[i]["link"], rs[i]["recv_t"], rs[i]["dbm"])
                    i += 1
                out = hm.update(t, x[4], True, False)
                during |= hm.blind and lo0 <= (t - T0) / 1000 <= lo1 + 1.0
                on += [((t - T0) / 1000, e["info"].get("reason")) for e in out["events"] if e["kind"] == "blind_on"]
        hit = [a for a, _ in on if lo0 <= a <= lo1 + 1.0]
        false = [a for a, _ in on if not (lo0 <= a <= lo1 + 1.0) and not (so0 <= a <= so1 + 3.5)]
        rows.append(dict(g, hit=during, latency_s=round(hit[0] - lo0, 2) if hit else None,
                         short=any(so0 <= a <= so1 + 3.5 for a, _ in on), false=len(false),
                         false_jump=len([1 for a, r in on if r == "jump" and a in false])))
    return rows


def replay_alert(res, plan, hyst=ALERT_HYST):
    """Re-run the no-movement alert with a hysteresis on "moving" (1 = the rule as written)."""
    T0 = rf.T0_MS
    sp = plan["spans"]
    a0 = sp["alert4"][0][0]
    w1 = sp["wave"][0][1]
    rows = []
    for h in hyst:
        watch, run_len, on = AL.Watch(limits=LIMITS), 0, []
        for x in res["ticks"]:
            p = None if x[1] is None else {"present": x[1] > 0, "zone": x[1] or None, "kind": x[2], "motion": x[3]}
            if p is not None and p["kind"] == "person":
                run_len = run_len + 1 if p["motion"] == "moving" else 0
                p["motion"] = "moving" if run_len >= h else "still"
            watch.on_pred(x[0], p)
            on += [(x[0] - T0) / 1000 for k, _ in watch.pop_events() if k == "alert_on"]
        good = [a for a in on if a0 + 8.0 <= a <= w1 + 0.5]
        rows.append({"hyst": h, "hit": bool(good), "latency_s": round(good[0] - a0, 2) if good else None,
                     "false": len(on) - len(good)})
    return rows


def replay_xray(res, plan, grid=XRAY_GRID):
    """Re-run the X-ray and the advisor on the same live readings and predicted kinds."""
    T0 = rf.T0_MS
    brain = res["brain"]
    sp = plan["spans"]
    ts1 = sp["tray_still"][0][1]
    still = sp["alert4"] + sp["still"]
    rows = []
    for g in grid:
        with patched(g):
            xr = X.Xray.from_nodes(NODES_DOC)
            i, rs = 0, res["live_rssi"]
            first_det, loc, adv, fp_s, still_obj = None, None, None, 0.0, False
            for x in res["ticks"]:
                t = x[0]
                while i < len(rs) and rs[i]["recv_t"] <= t:
                    if rs[i]["link"] in brain.base:
                        xr.add(rs[i]["link"], rs[i]["recv_t"], brain.base[rs[i]["link"]] - rs[i]["dbm"])
                    i += 1
                out = xr.update(t, x[2] if x[1] is not None else None)
                s = (t - T0) / 1000
                tray_on = plan["t_tray"] <= s < ts1 + 1.0
                if out["objects"] and not tray_on:
                    fp_s += 0.1
                    still_obj |= _in(s, still)
                if out["objects"] and tray_on:
                    first_det = first_det or s
                    if s < sp["tray_empty"][0][1]:
                        loc = min(math.dist(o["xy_m"], plan["tray"]) for o in out["objects"])
                    if adv is None:
                        a = advise(out["xray"], [], NODES_DOC, out["objects"])
                        adv = a["to_spot"] if a else None
        rows.append(dict(g, detected=first_det is not None,
                         detect_s=None if first_det is None else round(first_det - plan["t_tray"], 1),
                         loc_err_m=None if loc is None else round(loc, 3), fp_s=round(fp_s, 1),
                         still_obj=still_obj, advice=adv, advice_right=None if adv is None else adv in plan["best_spots"]))
    return rows


# ---------------------------------------------------------------- one session

def session(seed=0, env=None, cfg=None, live_person=None, wave=None, smoke=False, replays=True, proto=None):
    """Build, simulate, run and score one session. Returns a JSON-ready dict."""
    env = env or rf.Env()
    cfg = dict(DEFAULT_CFG, **(cfg or {}))
    t0 = time.perf_counter()
    sc, plan = build(seed, env, live_person, wave, smoke, proto)
    tl = rf.Timeline(sc)
    msgs = rf.messages(tl, seed=seed)
    t1 = time.perf_counter()
    with patched(cfg):
        res = drive(msgs, plan)
        metrics = score(tl, plan, res, msgs)
    t2 = time.perf_counter()
    out = {"seed": seed, "env": env.to_dict(), "cfg": cfg, "proto": plan["proto"], "live_person": plan["held"][0],
           "metrics": metrics, "sources": SOURCES}
    if replays and res["trained"]:
        out["checkin_grid"] = replay_checkin(res, plan)
        out["health_grid"] = replay_health(res, plan)
        out["xray_grid"] = replay_xray(res, plan)
        out["alert_grid"] = replay_alert(res, plan)
    out["timing"] = {"simulate_s": round(t1 - t0, 2), "brain_s": round(t2 - t1, 2),
                     "replay_s": round(time.perf_counter() - t2, 2), "messages": len(msgs),
                     "sim_minutes": round(tl.T / 60, 2)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="One simulated session through the real brain (SIMULATED).")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true", help="short session, no replays, checks it runs")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-replays", action="store_true")
    args = ap.parse_args(argv)
    out = session(seed=args.seed, smoke=args.smoke, replays=not (args.smoke or args.no_replays))
    if args.json:
        print(json.dumps(out, default=float))
        return
    print("SIMULATED session, seed", args.seed, "| brain sources:", out["sources"])
    for k, v in out["metrics"].items():
        print(f"  {k}: {v}")
    print("  timing:", out["timing"])
    if args.smoke and not out["metrics"]["trained"]:
        raise SystemExit("smoke: the model never trained")


if __name__ == "__main__":
    main()
