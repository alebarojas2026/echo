"""Turn lab/out/*.jsonl into tables (lab/out/tables.md) and SVG charts (lab/figs/). SIMULATED.

    python -m lab.analyze
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from lab import svg

HERE = Path(__file__).resolve().parent
OUT, FIGS = HERE / "out", HERE / "figs"

BEATS = [  # (metric, kind, label); kind "rate" = share of sessions, "mean" = average
    ("heldout_acc", "mean", "Zone accuracy, held-out walkers (true zone)"),
    ("heldout_acc_near", "mean", "  ... standing within 0.15 m of a link"),
    ("heldout_acc_far", "mean", "  ... standing over 0.3 m from every link"),
    ("live_zone_acc", "mean", "Live zone accuracy (marked spots and free walking)"),
    ("live_empty_acc", "mean", "Empty room reads empty"),
    ("checkin_hit", "rate", "Wave gives a check-in"),
    ("false_checkins_per_min", "mean", "False check-ins per minute with someone in"),
    ("alert_hit", "rate", "No-movement alert fires in zone 4 (10 s)"),
    ("false_alerts", "mean", "False no-movement alerts per session"),
    ("blind_hit", "rate", "SENSOR BLIND on a 6 s beacon outage"),
    ("blind_on_short_outage", "rate", "SENSOR BLIND on a 1.5 s outage (should not)"),
    ("false_blinds", "mean", "SENSOR BLIND with every beacon fine, per session"),
    ("object_kind_frac", "mean", "Tray alone classified as object (share of decisions)"),
    ("tray_as_person_frac", "mean", "Tray alone classified as a person"),
    ("person_as_object_frac", "mean", "Person classified as object"),
    ("object_detected", "rate", "X-ray lists the tray while the room is empty"),
    ("still_person_became_object", "rate", "A still person became an X-ray object"),
    ("advice_fired", "rate", "Router advice appears"),
    ("advice_right", "rate", "Advice picks a right spot (when it appears)"),
    ("pred_null_frac", "mean", "Share of live decisions withheld (pred null)"),
]
ENV_KNOBS = ["k_db", "coherence_s", "meas_db", "ble_chan_db", "drift_db", "scatter", "bystanders", "wifi_frame_hz",
             "phone_hz", "phone_miss", "burst_per_min", "burst_s", "throttle_per_min", "hand_db", "cam_fps",
             "cam_miss", "foot_noise_m", "cam_latency_ms"]


def load(stage):
    p = OUT / f"{stage}.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.open(encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except ValueError:   # a stage still being written
            pass
    return [r for r in rows if "error" not in r and r.get("metrics", {}).get("trained")]


def values(rows, key):
    v = [r["metrics"].get(key) for r in rows]
    return np.array([float(x) for x in v if x is not None])


def ci(v, kind):
    """Mean with a 95% interval: Wilson for shares of sessions, normal for averages."""
    n = len(v)
    if n == 0:
        return None, None, None, 0
    m = float(np.mean(v))
    if kind == "rate":
        z = 1.96
        c = (m + z * z / (2 * n)) / (1 + z * z / n)
        h = z * math.sqrt(m * (1 - m) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return m, max(0.0, c - h), min(1.0, c + h), n
    h = 1.96 * float(np.std(v, ddof=1)) / math.sqrt(n) if n > 1 else 0.0
    return m, m - h, m + h, n


def fmt(m, lo, hi, n):
    return "n/a" if m is None else f"{m:.2f} [{lo:.2f}, {hi:.2f}] (n={n})"


def beat_table(rows, title):
    out = [f"### {title}", "", "| Beat | SIMULATED value [95% CI] |", "|---|---|"]
    for key, kind, label in BEATS:
        out.append(f"| {label} | {fmt(*ci(values(rows, key), kind))} |")
    return out + [""]


def env_sensitivity(rows):
    """Spearman rho of each outcome against each environment knob, strongest first."""
    out = ["### What the outcomes depend on (environment sweep, Spearman rho)", "",
           "| Outcome | Strongest knobs (rho) |", "|---|---|"]
    for key, _, label in BEATS:
        y = [r["metrics"].get(key) for r in rows]
        pairs = []
        for k in ENV_KNOBS:
            xs = [r["env"][k] for r, v in zip(rows, y) if v is not None]
            ys = [float(v) for v in y if v is not None]
            if len(set(ys)) > 1 and len(ys) > 20:
                rho = spearmanr(xs, ys).statistic
                if abs(rho) >= 0.1:
                    pairs.append((abs(rho), k, rho))
        top = ", ".join(f"{k} ({rho:+.2f})" for _, k, rho in sorted(pairs, reverse=True)[:4]) or "none above 0.1"
        out.append(f"| {label.strip(' .')} | {top} |")
    return out + [""]


def binned(rows, knob, key, bins=5):
    """Outcome mean per quantile bin of a knob: [(bin centre, mean, n)]."""
    pts = [(r["env"][knob], float(r["metrics"][key])) for r in rows if r["metrics"].get(key) is not None]
    if len(pts) < bins * 5:
        return []
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    edges = np.quantile(xs, np.linspace(0, 1, bins + 1))
    res = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (xs >= a) & (xs <= b)
        res.append((float(np.mean(xs[sel])), float(np.mean(ys[sel])), int(sel.sum())))
    return res


def grid_table(rows, name, keys, cols):
    """Average a replay grid over sessions: one row per parameter combination."""
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for g in r.get(name, []):
            k = tuple(g[x] for x in keys)
            for c in cols:
                if g.get(c) is not None:
                    acc[k][c].append(float(g[c]))
    return {k: {c: (float(np.mean(v[c])) if v[c] else None, len(v[c])) for c in cols} for k, v in acc.items()}


def stage_table(rows, keys, title):
    groups = defaultdict(list)
    for r in rows:
        groups[r["tag"]].append(r)
    out = [f"### {title}", "", "| Setting | " + " | ".join(label for _, _, label in keys) + " |",
           "|---|" + "---|" * len(keys)]
    for tag in sorted(groups, key=_tag_order):
        cells = []
        for key, kind, _ in keys:
            m, lo, hi, n = ci(values(groups[tag], key), kind)
            cells.append("n/a" if m is None else f"{m:.2f} ±{(hi - lo) / 2:.2f}")
        out.append(f"| {tag} | " + " | ".join(cells) + " |")
    return out + [""], groups


def _tag_order(tag):
    head, _, tail = tag.rpartition(" ")
    try:
        return head, float(tail.lstrip("nd")) if tail != "dNone" else 1e9
    except ValueError:
        return tag, 0.0


def main():
    FIGS.mkdir(exist_ok=True)
    md = ["# Tables (SIMULATED, generated by lab/analyze.py)", ""]
    nominal, env = load("nominal"), load("env")
    with_grids = nominal + env
    if nominal:
        md += beat_table(nominal, "Nominal room (moderate hall, default brain settings)")
    if env:
        md += beat_table(env, "Wide environment sweep (default brain settings)")
        md += env_sensitivity(env)
        for knob, key, label, ylim in (("k_db", "heldout_acc", "Zone accuracy vs hall fading (K)", (0, 1)),
                                       ("k_db", "false_checkins_per_min", "False check-ins vs fading (K)", None),
                                       ("phone_hz", "blind_hit", "Blind on outage vs phone advert rate", (0, 1)),
                                       ("drift_db", "false_blinds", "False SENSOR BLIND vs slow drift", None)):
            b = binned(env, knob, key)
            if b:
                md += [f"Binned {key} by {knob}: " + ", ".join(f"{x:.2f} -> {y:.2f} (n={n})" for x, y, n in b), ""]
        b = binned(env, "k_db", "heldout_acc")
        b2 = binned(env, "k_db", "live_zone_acc")
        if b and b2:
            svg.lines(FIGS / "zone_vs_fading.svg", "Zone accuracy falls as the hall gets busier",
                      [("held-out walkers", [round(x, 1) for x, _, _ in b], [y for _, y, _ in b]),
                       ("live demo", [round(x, 1) for x, _, _ in b2], [y for _, y, _ in b2])],
                      "Rician K of the hall, dB (low = busier, more fading)", "share of decisions right")
    if with_grids:
        g = grid_table(with_grids, "checkin_grid", ["cross_db", "crossings", "cross_window_ms", "smooth_n"],
                       ["hit", "false_per_min", "latency_s"])
        md += ["### Check-in rule replay (all swept sessions)", "",
               "| cross dB | crossings | window ms | smooth n | wave hit | false / min | latency s |",
               "|---|---|---|---|---|---|---|"]
        ranked = sorted(g.items(), key=lambda kv: (-(kv[1]["hit"][0] or 0) + 2 * (kv[1]["false_per_min"][0] or 0)))
        for k, v in ranked[:12] + [kv for kv in g.items() if kv[0] == (1.5, 4, 2500, 3)]:
            md.append("| " + " | ".join(str(x) for x in k) + " | " +
                      " | ".join("n/a" if v[c][0] is None else f"{v[c][0]:.2f}" for c in ("hit", "false_per_min", "latency_s")) + " |")
        md.append("")
        pts = [(v["false_per_min"][0], v["hit"][0]) for v in g.values()]
        cur = g.get((1.5, 4, 2500, 3))
        svg.scatter(FIGS / "checkin_tradeoff.svg", "Check-in: every threshold trades waves caught for false fires",
                    pts, "false check-ins per minute with someone in the square", "share of waves caught",
                    (0, max(2.0, min(10.0, max(p[0] for p in pts)))), (0, 1),
                    mark=(cur["false_per_min"][0], cur["hit"][0], "contract default") if cur else None)
        h = grid_table(with_grids, "health_grid", ["stale_frac", "blind_after_s", "jump_db"],
                       ["hit", "latency_s", "short", "false", "false_jump"])
        md += ["### Link health replay", "",
               "| stale frac | blind after s | jump dB | outage caught | latency s | 1.5 s outage blinds | false blinds | of them jump |",
               "|---|---|---|---|---|---|---|---|"]
        for k in sorted(h):
            v = h[k]
            md.append("| " + " | ".join(str(x) for x in k) + " | " + " | ".join(
                "n/a" if v[c][0] is None else f"{v[c][0]:.2f}" for c in ("hit", "latency_s", "short", "false", "false_jump")) + " |")
        md.append("")
        jd = sorted({k[2] for k in h})
        svg.lines(FIGS / "health_jump.svg", "False SENSOR BLIND per session vs the jump threshold",
                  [(f"blind after {b:g} s", jd, [h.get((0.4, b, j), {}).get("false", (None,))[0] for j in jd])
                   for b in (2.0, 3.0, 4.0)], "jump rule threshold, dB", "false blinds per session",
                  ylim=(0, max(0.5, max((v["false"][0] or 0) for v in h.values()))))
        x = grid_table(with_grids, "xray_grid", ["alpha_rel", "static_std_db"],
                       ["detected", "detect_s", "loc_err_m", "fp_s", "still_obj", "advice_right"])
        md += ["### X-ray and advisor replay", "",
               "| alpha rel | static std dB | tray found | seconds to find | position error m | ghost object s | still person -> object | advice right |",
               "|---|---|---|---|---|---|---|---|"]
        for k in sorted(x):
            v = x[k]
            md.append("| " + " | ".join(str(z) for z in k) + " | " + " | ".join(
                "n/a" if v[c][0] is None else f"{v[c][0]:.2f}" for c in
                ("detected", "detect_s", "loc_err_m", "fp_s", "still_obj", "advice_right")) + " |")
        md.append("")
        stds = sorted({k[1] for k in x})
        svg.bars(FIGS / "xray_steady.svg", "The tray only shows up once the steadiness test loosens",
                 [f"{s:g} dB" for s in stds], [x[(0.1, s)]["detected"][0] for s in stds],
                 "X-ray static std threshold (contract: 0.8 dB)", "share of sessions the tray is found")
        a = grid_table(with_grids, "alert_grid", ["hyst"], ["hit", "latency_s", "false"])
        md += ["### No-movement alert replay (reset only after N moving decisions in a row)", "",
               "| N | alert fires | latency s | false alerts / session |", "|---|---|---|---|"]
        for k in sorted(a):
            md.append(f"| {k[0]} | " + " | ".join("n/a" if a[k][c][0] is None else f"{a[k][c][0]:.2f}"
                                                   for c in ("hit", "latency_s", "false")) + " |")
        md.append("")
        svg.bars(FIGS / "alert_hysteresis.svg", "No-movement alert: one 'moving' blip resets the timer",
                 [f"N = {k[0]}" for k in sorted(a)], [a[k]["hit"][0] for k in sorted(a)],
                 "reset the still timer after N moving decisions in a row (now N = 1)", "share of alerts that fire")
    keys = [("heldout_acc", "mean", "held-out zone"), ("live_zone_acc", "mean", "live zone"),
            ("live_empty_acc", "mean", "empty reads empty"), ("object_kind_frac", "mean", "tray = object"),
            ("alert_hit", "rate", "alert fires"), ("checkin_hit", "rate", "check-in"),
            ("object_detected", "rate", "X-ray tray")]
    for stage, title in (("forest", "Forest size and depth"), ("window", "Window length (contract: 1000 ms)"),
                         ("protocol", "Protocol: training, spots, tray, camera view"),
                         ("person", "The live person: speed, height, body depth")):
        rows = load(stage)
        if not rows:
            continue
        t, groups = stage_table(rows, keys, title + " (SIMULATED)")
        md += t
        if stage == "forest":
            ns = [10, 30, 60, 120]
            svg.lines(FIGS / "forest.svg", "Held-out zone accuracy vs forest size",
                      [(f"depth {d}", ns, [ci(values(groups.get(f"forest n{n} d{d}", []), "heldout_acc"), "mean")[0]
                                           for n in ns]) for d in (6, 12, None)],
                      "trees per forest", "share of windows right", ylim=(0.4, 1))
        if stage == "window":
            ws = [500, 750, 1000, 1500, 2000]
            svg.lines(FIGS / "window.svg", "Zone accuracy vs window length",
                      [(name, ws, [ci(values(groups.get(f"window {w}", []), key), "mean")[0] for w in ws])
                       for name, key in (("held-out", "heldout_acc"), ("live", "live_zone_acc"))],
                      "window length, ms", "share right", ylim=(0.4, 1))
        if stage == "protocol":
            vs = [1.0, 3.0, 5.0, 10.0]
            svg.lines(FIGS / "train_still.svg", "Alert and accuracy vs standing time while recording",
                      [(name, vs, [ci(values(groups.get(f"train_still_s {v}", []), key), kind)[0] for v in vs])
                       for name, key, kind in (("alert fires", "alert_hit", "rate"),
                                               ("held-out zone", "heldout_acc", "mean"))],
                      "seconds standing on each marked spot during training", "share", ylim=(0, 1))
    if nominal or env:
        allr = nominal + env
        dist = [("near (<0.15 m)", "heldout_acc_near"), ("0.15-0.3 m", "heldout_acc_mid"), ("far (>0.3 m)", "heldout_acc_far")]
        svg.bars(FIGS / "zone_vs_link_distance.svg", "Zone accuracy depends on standing near a link line",
                 [d[0] for d in dist], [ci(values(allr, k), "mean")[0] for _, k in dist],
                 "held-out walker's distance to the nearest link line", "share of windows right")
    (OUT / "tables.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
