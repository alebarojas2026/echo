"""Tables and charts from the desk-strip sessions. SIMULATED, dev only.

    python -m lab.desk_report                      # tables to stdout
    python -m lab.desk_report --charts some/dir    # also PNG charts (never committed: the repo takes no images)

Reads lab/out/desk_*.jsonl and lab/out/hall.jsonl. Every chart has people walking
past per minute on the x-axis, so a head count at the real desk picks the column.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
TODAY = "0.0/10/6"
STILL_TODAY = "mode=reset run_n=5 source=forest"


def load(*names):
    """Rows of the named files. A later file's row replaces an earlier one for the same tag, seed and rate."""
    rows, plain = {}, []
    for name in names:
        p = OUT / name
        if p.exists():
            with p.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        r = json.loads(line)
                        if "tag" in r:
                            rows[(r["tag"], r["seed"], r["rate"])] = r
                        else:
                            plain.append(r)
    return list(rows.values()) + plain


def groups(rows):
    g = collections.defaultdict(list)
    for r in rows:
        if "error" not in r:
            g[(r["tag"], r["rate"])].append(r["metrics"])
    return g


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def summary(M):
    """One row of numbers for a list of session metrics."""
    ok = [m for m in M if "armed" in m]
    out = {"n": len(M), "ran": len(ok) / max(len(M), 1),
           "baseline_s": _med([m.get("desk_baseline_s") for m in M]),
           "baseline_late": _mean([(m.get("desk_baseline_s") or 999) > 60 for m in M if m.get("keep_model")]),
           "blind_frac": _mean([m["blind_s"] / m["live_s"] for m in M if m.get("live_s")])}
    if not ok:
        return out
    em = sum(m["empty_min"] for m in ok) or 1e-9
    for k in ("present_empty", "present_short", "present_up", "zone_ok_up", "zone_ok_left", "zone_ok_still",
              "moving_still", "moving_fidget", "base_err_db", "blind_s"):
        out[k] = _mean([m.get(k) for m in ok])
    out["passers_per_min"] = sum(m["passers_alone"] for m in ok) / em
    out["armed"] = {}
    for key in ok[0]["armed"]:
        a = [m["armed"][key] for m in ok]
        out["armed"][key] = {
            "false_per_min": sum(x["false_in"] + x["false_out"] + x["noise"] for x in a) / em,
            "passed_by_per_min": sum(x["passed_by"] for x in a) / em,
            "intruder": _mean([x["intruder"] for x in a]), "intruder_s": _med([x["intruder_s"] for x in a]),
            "through_intrusion": _mean([x["through"] == "intrusion" for x in a]),
            "through_passed": _mean([x["through"] == "passed_by" for x in a]),
            "brush_intrusion": _mean([x["brush"] == "intrusion" for x in a]),
            "visit1": _mean([x["visit1"] for x in a]), "while_back": _mean([x["visit1_while_back"] for x in a])}
    out["found"] = {}
    for key in ok[0]["found"]:
        a = [m["found"][key] for m in ok]
        out["found"][key] = {"false_shown_per_min": sum(x["false_shown"] for x in a) / em,
                             "false_opened_per_min": sum(x["false_opened"] for x in a) / em,
                             "found": _mean([x["found_s"] is not None for x in a]),
                             "found_s": _med([x["found_s"] for x in a]),
                             "opened": _mean([x["open_s"] is not None for x in a]),
                             "open_s": _med([x["open_s"] for x in a])}
    out["still"] = {}
    for key in ok[0]["still"]:
        a = [m["still"][key] for m in ok]
        out["still"][key] = {"hit": _mean([x["hit"] for x in a]), "late_s": _med([x["late_s"] for x in a]),
                             "early": _mean([x["early"] for x in a]), "pacer": _mean([x["fidget"] for x in a]),
                             "other_per_session": _mean([x["other"] for x in a])}
    return out


def table(rows, tags=None, armed=(TODAY, "1.0/10/6", "2.0/10/6", "3.0/10/6", "2.0/10/8"), out=print):
    g = groups(rows)
    names = tags or sorted({t for t, _ in g})
    rates = sorted({r for _, r in g})
    for tag in names:
        out(f"\n== {tag}")
        out("rate   n  ran ghost p40cm p_up zoneL | false/min " + " ".join(f"{a:>9}" for a in armed)
            + " | intruder " + " ".join(f"{a:>9}" for a in armed) + " | still hit/pacer today  base_s late")
        for r in rates:
            if (tag, r) not in g:
                continue
            s = summary(g[(tag, r)])
            if "armed" not in s:
                out(f"{r:>4} {s['n']:>3} {s['ran']:.2f}  (no decisions)")
                continue
            f = lambda v: "   -" if v is None else f"{v:4.2f}"   # noqa: E731
            st = s["still"][STILL_TODAY]
            out(f"{r:>4} {s['n']:>3} {s['ran']:.2f} {f(s['present_empty'])} {f(s['present_short'])} {f(s['present_up'])} "
                f"{f(s['zone_ok_left'])} |           " + " ".join(f"{s['armed'][a]['false_per_min']:9.2f}" for a in armed)
                + " |          " + " ".join(f"{s['armed'][a]['intruder']:9.2f}" for a in armed)
                + f" | {f(st['hit'])} {f(st['pacer'])}   {s['baseline_s'] or 0:5.1f} {f(s['baseline_late'])}")


def charts(rows, hall_rows, folder):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    g = groups(rows)
    S = {k: summary(v) for k, v in g.items()}
    rates = sorted({r for _, r in g})
    ink, grid = "#22262b", "#d9dde2"
    colours = ["#c2410c", "#1d4ed8", "#15803d", "#7c3aed", "#b45309", "#0f766e", "#be185d", "#475569"]
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": ink, "axes.labelcolor": ink, "text.color": ink,
                         "xtick.color": ink, "ytick.color": ink, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": grid, "figure.dpi": 130})

    def series(tag, fn):
        xs = [r for r in rates if (tag, r) in S and "armed" in S[(tag, r)]]
        return xs, [fn(S[(tag, r)]) for r in xs]

    def panel(ax, lines, title, ylabel, ylim=None):
        for k, (label, tag, fn) in enumerate(lines):
            xs, ys = series(tag, fn)
            if xs:
                ax.plot(xs, ys, marker="o", ms=3.5, lw=1.8, color=colours[k % len(colours)], label=label)
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold")
        ax.set_xlabel("people walking past per minute")
        ax.set_ylabel(ylabel)
        if ylim:
            ax.set_ylim(*ylim)
        else:
            ax.set_ylim(bottom=0)
        ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.0, 1.0))

    def save(fig, name):
        fig.suptitle("SIMULATED: ranks settings, does not measure them", x=0.01, ha="left", fontsize=9, color="#b91c1c")
        fig.tight_layout(rect=(0, 0, 1, 0.96))
        fig.savefig(folder / name)
        plt.close(fig)

    arm = lambda key, f: (lambda s: s["armed"][key][f])     # noqa: E731
    still = lambda key, f: (lambda s: s["still"][key][f])   # noqa: E731
    found = lambda key, f: (lambda s: s["found"][key][f])   # noqa: E731

    waits = [("today: fires at once", TODAY), ("wait 1 s", "1.0/10/6"), ("wait 2 s", "2.0/10/6"),
             ("wait 3 s", "3.0/10/6"), ("wait 4 s", "4.0/10/6"), ("8 of 10, wait 2 s", "2.0/10/8"),
             ("16 of 20, wait 2 s", "2.0/20/16")]
    fig, ax = plt.subplots(2, 2, figsize=(14, 7.6), sharey="row")
    for col, (plan, name) in enumerate((("A ref", "tonight's training plan"), ("B ref", "better training"))):
        panel(ax[0][col], [(lb, plan, arm(k, "false_per_min")) for lb, k in waits],
              f"False intrusions, {name}", "per minute of empty, armed strip")
        panel(ax[1][col], [(lb, plan, arm(k, "intruder")) for lb, k in waits],
              f"A person who steps in for 5-8 s is reported, {name}", "share of sessions", (0, 1.02))
    save(fig, "desk-twin-armed.png")

    sv = [("today: reset after 0.5 s moving", STILL_TODAY), ("reset after 1 s", "mode=reset run_n=10 source=forest"),
          ("reset after 2 s", "mode=reset run_n=20 source=forest"),
          ("pause, clear after 2 s", "mode=pause pause_reset_n=20 run_n=5 source=forest"),
          ("zone's own links, 3 dB", "mode=reset run_n=5 source=zone std_db=3.0"),
          ("zone's own links, 2 dB", "mode=reset run_n=5 source=zone std_db=2.0"),
          ("own links 3 dB + pause", "mode=pause pause_reset_n=20 run_n=5 source=zone std_db=3.0")]
    fig, ax = plt.subplots(1, 2, figsize=(15, 4.2))
    panel(ax[0], [(lb, "B ref", still(k, "hit")) for lb, k in sv], "No-movement alert fires on a 15 s stand",
          "share of sessions", (0, 1.02))
    panel(ax[1], [(lb, "B ref", still(k, "pacer")) for lb, k in sv], "... and on someone pacing (should be 0)",
          "share of sessions", (0, 1.02))
    save(fig, "desk-twin-still.png")

    fig, ax = plt.subplots(3, 2, figsize=(15, 11))
    ax = [[ax[0][0], ax[0][1], ax[1][0]], [ax[1][1], ax[2][0], ax[2][1]]]
    w2 = "2.0/10/6"
    panel(ax[0][0], [("twelve links", "B ref", arm(w2, "false_per_min")), ("the six on main", "B links six", arm(w2, "false_per_min")),
                     ("four strip-crossing", "B links cross", arm(w2, "false_per_min")),
                     ("crossing + strip ends", "B links cross+ends", arm(w2, "false_per_min"))],
          "Which links decide: false intrusions (wait 2 s)", "per minute of empty strip")
    panel(ax[0][1], [("twelve links", "B ref", lambda s: s["zone_ok_left"]), ("the six on main", "B links six", lambda s: s["zone_ok_left"]),
                     ("four strip-crossing", "B links cross", lambda s: s["zone_ok_left"]),
                     ("crossing + strip ends", "B links cross+ends", lambda s: s["zone_ok_left"])],
          "... and the side is right after a step left", "share of decisions", (0, 1.02))
    panel(ax[0][2], [(f"arm reach {r} m", "B ref" if r == 0.35 else f"B reach {r}", arm(w2, "false_per_min"))
                     for r in (0.15, 0.25, 0.35, 0.45)], "Arm reach: false intrusions (wait 2 s)", "per minute of empty strip")
    panel(ax[1][0], [(f"arm reach {r} m", "B ref" if r == 0.35 else f"B reach {r}", lambda s: s["present_short"])
                     for r in (0.15, 0.25, 0.35, 0.45)], "Arm reach: a judge 40 cm back is seen", "share of decisions", (0, 1.02))
    panel(ax[1][1], [("median of 20 s (today)", "B ref", lambda s: s["present_empty"]), ("mean of 20 s", "B baseline mean", lambda s: s["present_empty"]),
                     ("quietest 20 s of 60", "B baseline quiet", lambda s: s["present_empty"]),
                     ("median, people in the strip", "B baseline open", lambda s: s["present_empty"])],
          "Desk baseline: empty strip read as a person", "share of decisions", (0, 1.02))
    panel(ax[1][2], [("tonight's plan", "A ref", lambda s: s["present_empty"]), ("+ aisle walker recorded", "A train aisle", lambda s: s["present_empty"]),
                     ("no labels behind the arm line", "A train no back", lambda s: s["present_empty"]),
                     ("empty recording 3 x 20 s", "A train empty split", lambda s: s["present_empty"]),
                     ("both (better training)", "B ref", lambda s: s["present_empty"]),
                     ("better + aisle walker", "B train aisle", lambda s: s["present_empty"])],
          "Training plan: empty strip read as a person", "share of decisions", (0, 1.02))
    save(fig, "desk-twin-layout.png")

    fv = [("today: at once", "1/3.0"), ("after 0.5 s", "5/3.0"), ("after 1 s", "10/3.0"), ("after 1.5 s", "15/3.0"),
          ("after 2 s", "20/3.0")]
    fig, ax = plt.subplots(1, 3, figsize=(18, 4.2))
    panel(ax[0], [(lb, "B ref", found(k, "false_shown_per_min")) for lb, k in fv],
          '"Found you." shown with nobody at the desk', "per minute of empty strip")
    panel(ax[1], [(lb, "B ref", found(k, "found_s")) for lb, k in fv],
          "A judge is found this long after stopping 40 cm back", "seconds (median)")
    panel(ax[2], [("hold 3 s, shown at once", "B ref", found("1/3.0", "false_opened_per_min")),
                  ("hold 3 s, shown after 1 s", "B ref", found("10/3.0", "false_opened_per_min")),
                  ("hold 2 s, shown after 1 s", "B ref", found("10/2.0", "false_opened_per_min")),
                  ("hold 1 s, shown after 1 s", "B ref", found("10/1.0", "false_opened_per_min"))],
          "The room opens with nobody at the desk", "per minute of empty strip")
    save(fig, "desk-twin-found.png")

    if hall_rows:
        H = collections.defaultdict(list)
        for r in hall_rows:
            if "error" not in r:
                H[r["people"]].append(r)
        ns = sorted(H)
        fig, ax = plt.subplots(1, 3, figsize=(14, 4.2))
        for k, (rule_, label) in enumerate((("own", "quiet level: the link's own last 5 min (#389)"),
                                            ("empty", "quiet level kept from the empty hall"),
                                            ("honest", 'empty-hall level + "path busy" when it is'))):
            a = ax[k]
            for j, (f, lb) in enumerate((("hit", "on when our walker crosses"), ("false", "on when they are far away"),
                                         ("on_frac", "share of time on"))):
                a.plot(range(len(ns)), [_mean([r[rule_][f] for r in H[n]]) for n in ns], marker="o", ms=3.5, lw=1.8,
                       color=colours[j], label=lb)
            if rule_ == "honest":
                a.plot(range(len(ns)), [_mean([r["busy_frac"] for r in H[n]]) for n in ns], marker="o", ms=3.5, lw=1.8,
                       color=colours[3], label='"path busy" shown')
            a.set_xticks(range(len(ns)))
            a.set_xticklabels([str(n) for n in ns])
            a.set_ylim(0, 1.02)
            a.set_xlabel("people in the hall")
            a.set_ylabel("share")
            a.set_title(label, loc="left", fontsize=10, fontweight="bold")
            a.legend(frameon=False, fontsize=8, loc="center left")
        save(fig, "desk-twin-hall.png")


def hall_table(hall_rows, out=print):
    H = collections.defaultdict(list)
    for r in hall_rows:
        if "error" not in r:
            H[(r["people"], r["walk_share"])].append(r)
    out("\n== hall paths: people walk  n | quiet own/empty dB | own: on hit false | empty-level: on hit false | busy shown")
    for (n, w) in sorted(H):
        v = H[(n, w)]
        m = lambda rule_, f: _mean([r[rule_][f] for r in v])   # noqa: E731
        out(f"{n:>4} {w:.2f} {len(v):>3} | {_mean([r['quiet_own_db'] for r in v]):.2f} {_mean([r['quiet_empty_db'] for r in v]):.2f} | "
            f"{m('own', 'on_frac'):.2f} {m('own', 'hit'):.2f} {m('own', 'false'):.2f} | "
            f"{m('empty', 'on_frac'):.2f} {m('empty', 'hit'):.2f} {m('empty', 'false'):.2f} | {_mean([r['busy_frac'] for r in v]):.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Tables and charts from the desk sessions (SIMULATED).")
    ap.add_argument("--charts", help="folder for PNG charts")
    ap.add_argument("--files", nargs="*", default=["desk_sweep.jsonl", "desk_visits.jsonl", "desk_today.jsonl", "desk_reach.jsonl"])
    a = ap.parse_args(argv)
    rows = load(*a.files)
    hall_rows = load("hall.jsonl")
    print(f"SIMULATED. {len(rows)} desk sessions ({sum('error' in r for r in rows)} errors), {len(hall_rows)} hall sessions")
    table(rows)
    if hall_rows:
        hall_table(hall_rows)
    if a.charts:
        charts(rows, hall_rows, a.charts)
        print("charts in", a.charts)


if __name__ == "__main__":
    main()
