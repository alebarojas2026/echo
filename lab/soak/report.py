"""Sum up a farm round (simulated): what broke, on how many days, and what grows per hour.

    python lab/soak/report.py lab/soak/farm-runs/r1            # Markdown to stdout
    python lab/soak/report.py lab/soak/farm-runs/r1 --json     # the same as JSON

Reads every day folder (<tree>-<pace>-s<seed>/) that lab/soak/day.py wrote. Growth is a straight-line
fit per process over one process lifetime (a restart starts a new one), after the first 15 minutes.
Only what goes wrong and what grows is reported: never timings, which on x86 say nothing about the board.
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

WARMUP_S = 900
FLAG_MB_H = 10.0
FLAG_FD_H = 10.0


def lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def slope(points):
    """Least squares slope of (t seconds, y) in y per hour, or None with too little to fit."""
    if len(points) < 6 or points[-1][0] - points[0][0] < 1200:
        return None
    ts, ys = [p[0] for p in points], [p[1] for p in points]
    mt, my = statistics.fmean(ts), statistics.fmean(ys)
    den = sum((t - mt) ** 2 for t in ts)
    return None if den == 0 else sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / den * 3600


def day_growth(folder):
    by_pid, disk, t0 = defaultdict(list), [], None
    for r in lines(folder / "procs.jsonl"):
        t0 = t0 if t0 is not None else r["t"]
        if r["proc"] == "disk":
            disk.append(r)
        elif "rss" in r:
            by_pid[(r["proc"], r["pid"])].append(r)
    grow = defaultdict(dict)
    for (proc, _), rows in by_pid.items():
        rows = [r for r in rows if r["t"] - rows[0]["t"] >= WARMUP_S] if rows[-1]["t"] - rows[0]["t"] > 2 * WARMUP_S else rows
        for key, scale in (("rss", 1 / 2 ** 20), ("fds", 1), ("threads", 1)):
            s = slope([(r["t"], r[key] * scale) for r in rows if key in r])
            span = rows[-1]["t"] - rows[0]["t"] if rows else 0
            if s is not None and span > grow[proc].get(key + "_span", 0):
                grow[proc][key] = round(s, 2)
                grow[proc][key + "_span"] = span
                grow[proc][key + "_last"] = round(rows[-1][key] * scale, 1)
    files = {}
    for key in ("store.db", "store.db-wal", "sessions", "logs"):
        s = slope([(r["t"], r.get(key, 0) / 2 ** 20) for r in disk])
        if s is not None:
            files[key] = {"mb_per_h": round(s, 2), "last_mb": round(disk[-1].get(key, 0) / 2 ** 20, 2)}
    return grow, files


def load(root):
    days = []
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir() and (p / "summary.json").exists()):
        s = json.loads((folder / "summary.json").read_text())
        cfg = next(lines(folder / "config.jsonl"), {})
        grow, files = day_growth(folder)
        schema = [r for r in lines(folder / "monitor.jsonl") if r.get("kind") == "schema"]
        visits = list(lines(folder / "visits.jsonl"))
        days.append({"name": folder.name, "tree": folder.name.split("-")[0], "pace": folder.name.split("-")[1],
                     "summary": s, "cfg": cfg, "growth": grow, "files": files, "schema": schema, "visits": visits,
                     "problems": list(lines(folder / "problems.jsonl"))})
    return days


def build(days):
    out = {"trees": {}, "problems": {}, "contract": {}, "growth": {}, "files": {}}
    for d in days:
        t = out["trees"].setdefault(d["tree"], {"days": 0, "hours": 0.0, "visits": 0, "heads": set(), "final": 0})
        t["days"] += 1
        t["hours"] += d["summary"].get("hours_run", 0)
        t["visits"] += d["summary"].get("visits", 0)
        t["final"] += bool(d["summary"].get("final"))
        t["heads"].add(((d["cfg"].get("repo_head")) or "?").split(" ")[-1][:10])
        for p in d["problems"]:
            sig = (d["tree"], p["kind"], str(p.get("key")))
            g = out["problems"].setdefault(sig, {"count": 0, "days": set(), "first": None})
            g["count"] += 1
            g["days"].add(d["name"])
            if g["first"] is None:
                g["first"] = dict(p, day=d["name"], seed=d["cfg"].get("cfg", {}).get("seed"))
        for key, n in (d["summary"].get("contract") or {}).items():
            g = out["contract"].setdefault((d["tree"], key), {"count": 0, "days": set(), "example": None})
            g["count"] += n
            g["days"].add(d["name"])
            ex = next((x for x in d["schema"] if f"{x.get('type')} {x['errors'][0].split(':')[0]}" == key), None)
            if ex and g["example"] is None:
                g["example"] = {"errors": ex["errors"][:3], "day": d["name"]}
        for proc, gr in d["growth"].items():
            for key in ("rss", "fds", "threads"):
                if key in gr:
                    out["growth"].setdefault((d["tree"], d["pace"], proc, key), []).append((gr[key], d["name"], gr[key + "_last"]))
        for key, v in d["files"].items():
            out["files"].setdefault((d["tree"], d["pace"], key), []).append(v["mb_per_h"])
    return out


def markdown(r):
    md = ["# Soak farm round (simulated)", ""]
    for tree, t in r["trees"].items():
        md.append(f"- **{tree}** ({', '.join(sorted(t['heads']))}): {t['days']} days ({t['final']} finished), "
                  f"{t['hours']:.1f} simulated hours, {t['visits']} judge visits")
    md += ["", "## What broke", "", "| tree | kind | key | times | days | first seen |", "|---|---|---|---|---|---|"]
    for (tree, kind, key), g in sorted(r["problems"].items(), key=lambda kv: -len(kv[1]["days"])):
        f = g["first"]
        md.append(f"| {tree} | {kind} | {key[:70]} | {g['count']} | {len(g['days'])} | {f['day']} visit {f.get('visit')} {f.get('segment')} |")
    md += ["", "## Out of contract", "", "| tree | where | messages | days | example |", "|---|---|---|---|---|"]
    for (tree, key), g in sorted(r["contract"].items(), key=lambda kv: -kv[1]["count"]):
        ex = (g["example"] or {}).get("errors", [""])[0][:110]
        md.append(f"| {tree} | {key} | {g['count']} | {len(g['days'])} | {ex} |")
    md += ["", "## Growth per hour (median, worst; flagged over "
           f"{FLAG_MB_H} MB/h or {FLAG_FD_H} fds/h)", "", "| tree | pace | process | what | median | worst | worst day |",
           "|---|---|---|---|---|---|---|"]
    for (tree, pace, proc, key), vals in sorted(r["growth"].items()):
        vals.sort()
        med, worst = statistics.median(v[0] for v in vals), vals[-1]
        flag = " **flag**" if (key == "rss" and worst[0] > FLAG_MB_H) or (key == "fds" and worst[0] > FLAG_FD_H) else ""
        unit = "MB/h" if key == "rss" else "/h"
        md.append(f"| {tree} | {pace} | {proc} | {key} | {med:.2f} {unit} | {worst[0]:.2f}{flag} | {worst[1]} |")
    md += ["", "## Files per hour (median MB/h)", ""]
    for (tree, pace, key), vals in sorted(r["files"].items()):
        md.append(f"- {tree} {pace} {key}: {statistics.median(vals):.2f} MB/h (worst {max(vals):.2f}, {len(vals)} days)")
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("root")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = build(load(a.root))
    if a.json:
        print(json.dumps({k: {str(kk): vv for kk, vv in v.items()} for k, v in r.items()}, default=lambda o: sorted(o) if isinstance(o, set) else str(o), indent=1))
    else:
        print(markdown(r))


if __name__ == "__main__":
    main()
