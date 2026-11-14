"""Cheap replays: the same recorded live stream through other thresholds. SIMULATED.

A full session (lab/run.py) records the live readings and every decision.
These re-run one rule at a time on that record with other settings, so the
settings are compared on exactly the same room:
  - check-in (brain/alert.py CheckIn), plus a variant that only counts a
    check-in while the person reads still;
  - the no-movement alert with a hysteresis on "moving";
  - link health (brain/health.py);
  - the X-ray objects (brain/xray.py) and the advisor.
"""
from __future__ import annotations

import math

from advisor.advise import advise
from brain import alert as AL
from brain import health as H
from brain import xray as X
from lab import rf
from lab.run import LIMITS, NODES_DOC, _in, patched


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


