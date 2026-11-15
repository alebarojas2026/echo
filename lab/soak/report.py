"""Turn a soak run folder into the numbers for RESULTS.md.

    python lab/soak/report.py lab/soak/runs/r1      # prints markdown, writes report.json there
"""
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contracts.check import check_lines  # noqa: E402

QUIET = {"stand_still": "still", "empty_room": "empty", "metal_object": "empty"}  # no wave, no expected check-in
ALERT_OK = {"stand_still", "wave_checkin"}   # someone stands still in zone 4 past its 10 s limit


def jsonl(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def slope_per_h(points):
    """Least-squares slope of (t s, value) in value per hour."""
    if len(points) < 3:
        return None
    mt = statistics.fmean(t for t, _ in points)
    mv = statistics.fmean(v for _, v in points)
    den = sum((t - mt) ** 2 for t, _ in points)
    return sum((t - mt) * (v - mv) for t, v in points) / den * 3600 if den else None


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def main(folder):
    run = Path(folder)
    summ = json.loads((run / "summary.json").read_text())
    mon, chaos, segs = jsonl(run / "monitor.jsonl"), jsonl(run / "chaos.jsonl"), jsonl(run / "segments.jsonl")
    procs, probe = jsonl(run / "procs.jsonl"), jsonl(run / "probe.jsonl")
    pauses = [p for p in jsonl(run / "proxy.jsonl") if "gap_s" in p]   # the test rig's own stalls
    rig_pause = lambda t: any(p["gap_s"] >= 1.0 and t - 8 <= p["t"] <= t for p in pauses)  # noqa: E731
    hours = (summ["now"] - summ["start"]) / 3600
    r = {"hours": round(hours, 2), "messages": summ["counts"], "proxy": summ["proxy"], "starts": summ["starts"]}
    kills = [c for c in chaos if c.get("kind") == "kill"]
    down = [(k["t"], next((c["t"] for c in chaos if c.get("kind") == "start" and c["proc"] == k["proc"] and c["t"] > k["t"]), k["t"]) + 15)
            for k in kills if k["proc"] == "brain"]
    in_down = lambda t: any(a - 1 <= t <= b for a, b in down)  # noqa: E731

    # State rate, in 10 s buckets away from brain restarts, and its drift over the run
    buckets = {int(k): v for k, v in summ["rate"].items()}
    rates = [v / 10 for k, v in sorted(buckets.items()) if not in_down(k) and not in_down(k + 10)][1:-1]
    halves = defaultdict(list)
    for k, v in sorted(buckets.items()):
        if not in_down(k) and not in_down(k + 10):
            halves[int((k - summ["start"]) // 1800)].append(v / 10)
    gaps = [m for m in mon if m["kind"] == "gap"]
    r["state_rate"] = {"median": statistics.median(rates), "p1": pct(rates, 0.01), "min": min(rates), "max": max(rates),
                       "per_half_hour": [round(statistics.fmean(v), 2) for _, v in sorted(halves.items())],
                       "gaps_over_1s": len(gaps), "gaps_not_restart": [g for g in gaps if not in_down(g["t"])]}

    # Memory and handles per process lifetime (first 5 min of each skipped as warm-up)
    life = defaultdict(list)
    for p in procs:
        if p.get("rss") and p["proc"] not in ("system", "disk"):
            life[(p["proc"], p["pid"])].append(p)
    mem = []
    for (name, pid), xs in life.items():
        xs = [x for x in xs if x["t"] - xs[0]["t"] >= 300] or xs
        mins = (xs[-1]["t"] - xs[0]["t"]) / 60
        if mins < 10:
            continue
        mem.append({"proc": name, "pid": pid, "minutes": round(mins), "rss_mb_start": round(xs[0]["rss"] / 2**20),
                    "rss_mb_end": round(xs[-1]["rss"] / 2**20), "rss_mb_max": round(max(x["rss"] for x in xs) / 2**20),
                    "rss_mb_per_h": round(slope_per_h([(x["t"], x["rss"] / 2**20) for x in xs]) or 0, 1),
                    "handles_start": xs[0]["handles"], "handles_end": xs[-1]["handles"],
                    "handles_per_h": round(slope_per_h([(x["t"], x["handles"]) for x in xs]) or 0, 1),
                    "cpu_median": statistics.median(x["cpu"] for x in xs)})
    r["memory"] = sorted(mem, key=lambda m: (m["proc"], -m["minutes"]))
    sysc = [p["cpu"] for p in procs if p["proc"] == "system"]
    r["system_cpu_median"] = statistics.median(sysc) if sysc else None

    # Exceptions and warnings in the logs
    logs = {}
    for f in sorted((run / "logs").glob("*.log")):
        text = f.read_text(encoding="utf-8", errors="replace")
        tb = text.count("Traceback (most recent call last)")
        lines = [ln for ln in text.splitlines() if re.search(r"Error|Exception|WARNING|warning|failed", ln)]
        top = Counter(re.sub(r"\d+", "N", ln.split("] ")[-1])[:140] for ln in lines).most_common(6)
        logs[f.stem] = {"tracebacks": tb, "error_lines": len(lines), "top": top}
    r["logs"] = logs

    # Recovery after restarts, as the monitor and the screen saw it
    rec = []
    for c in chaos:
        if c.get("kind") == "chaos" and c["action"] in ("brain", "bus"):
            t1 = c["restart_at"]
            seen = [p for p in probe if p.get("kind") == "dom" and c["start"] - 1 <= p["t"] / 1000 <= c["end"] + 60]
            nd = [p for p in seen if p["no_data"]]
            back = next((p["t"] / 1000 - t1 for p in seen if p["t"] / 1000 > t1 and not p["no_data"] and nd and p["t"] > nd[0]["t"]), None)
            rec.append({"proc": c["action"], "at_min": round((c["start"] - summ["start"]) / 60, 1),
                        "state_back_s": c.get("state_back_s"), "screen_no_data": bool(nd),
                        "screen_live_s": None if back is None else round(back, 1), "pred_back_s": c.get("pred_back_s"), "retrained": c.get("retrained"),
                        "links_ok_s": c.get("links_ok_s"), "blind_on_screen": any(p["blind"] for p in seen)})
    r["recovery"] = rec

    # Other faults
    r["faults"] = [{k: v for k, v in c.items() if k not in ("kind", "end")} | {"at_min": round((c["start"] - summ["start"]) / 60, 1)}
                   for c in chaos if c.get("kind") == "chaos" and c["action"] not in ("brain", "bus")]

    # False check-ins and alerts per hour of each path (training excluded), clean vs during a fault
    play = defaultdict(float)
    for s in segs:
        if not s["training"]:
            play[s["path"]] += (s["end"] - s["start"]) / 3600
    evs = [m for m in mon if m["kind"] == "event" and not m.get("training")]
    table = {}
    for path, h in sorted(play.items()):
        mine = [e for e in evs if e.get("path") == path]
        ci = [e for e in mine if e["ev"] == "checkin"]
        al = [e for e in mine if e["ev"] == "alert_on"]
        table[path] = {"hours": round(h, 2), "checkins": len(ci), "alerts": len(al),
                       "object_on": sum(1 for e in mine if e["ev"] == "object_on"),
                       "checkins_in_fault": sum(1 for e in ci if e.get("chaos")), "alerts_in_fault": sum(1 for e in al if e.get("chaos")),
                       "false_checkins_per_h": round(len(ci) / h, 1) if path != "wave_checkin" else None,
                       "false_alerts_per_h": round(len(al) / h, 1) if path not in ALERT_OK else None,
                       "plays": sum(1 for s in segs if s["path"] == path and not s["training"])}
    r["alarms"] = table

    # SENSOR BLIND episodes and what explains each one
    blind = [m for m in mon if m["kind"] == "event" and m["ev"] in ("blind_on", "blind_off")]
    eps, on = [], None
    for b in blind:
        if b["ev"] == "blind_on":
            on = b
        elif on:
            eps.append({"start": on["t"], "s": round(b["t"] - on["t"], 1), "path": on.get("path"), "chaos": on.get("chaos"),
                        "info": on.get("info")})
            on = None
    def cause(e):
        if e["chaos"]:
            return "fault: " + e["chaos"]
        if e["path"] == "dropped_link":
            return "path: dropped_link"
        return "rig: feed paused" if rig_pause(e["start"]) else "unexplained"
    for e in eps:
        e["cause"] = cause(e)
    why = Counter(e["cause"] for e in eps)
    r["blind"] = {"episodes": len(eps), "by_cause": why, "shorter_than_5s": sum(1 for e in eps if e["s"] < 5),
                  "unexplained": [e for e in eps if e["cause"] == "unexplained"][:20]}
    r["rig_pauses"] = {"count": len(pauses), "over_1s": sum(1 for p in pauses if p["gap_s"] >= 1.0),
                       "longest_s": max((p["gap_s"] for p in pauses), default=0)}

    # Contract checks: everything the monitor saw, then every recorded session file
    bad = Counter()
    for k, v in summ["bad"].items():
        bad[re.sub(r"\[\d+\]", "[i]", k)] += v
    r["contract_ws"] = {"checked": sum(summ["counts"].values()), "errors": dict(bad)}
    files = {}
    for f in sorted((run / "sessions").glob("*.jsonl")):
        n, fails, _ = check_lines(f.read_text(encoding="utf-8").splitlines())
        kinds = Counter(re.sub(r"\[\d+\]", "[i]", e.split(":")[0]) for _, e in fails)
        files[f.name] = {"bytes": f.stat().st_size, "lines": n, "bad": len(fails), "errors": dict(kinds.most_common(5))}
    r["sessions"] = files

    # The screen: NO DATA episodes, blind shown, heap and DOM growth, page errors
    dom = [p for p in probe if p.get("kind") == "dom"]
    nd_eps, cur = [], None
    for p in dom:
        if p["no_data"] and cur is None:
            cur = p["t"] / 1000
        elif not p["no_data"] and cur is not None:
            nd_eps.append((cur, p["t"] / 1000 - cur))
            cur = None
    mid = dom[len(dom) // 10:] if dom else []
    r["screen"] = {"samples": len(dom), "no_data_episodes": len(nd_eps),
                   "no_data_not_restart": [round(d, 1) for t, d in nd_eps if not in_down(t) and t > summ["start"] + 60],
                   "still_no_data_at_end": cur is not None,
                   "heap_mb_start": round(mid[0]["heap"] / 2**20, 1) if mid else None,
                   "heap_mb_end": round(mid[-1]["heap"] / 2**20, 1) if mid else None,
                   "heap_mb_per_h": round(slope_per_h([(p["t"] / 1000, p["heap"] / 2**20) for p in mid]) or 0, 2),
                   "dom_nodes": [min(p["nodes"] for p in dom), max(p["nodes"] for p in dom)] if dom else None,
                   "ws_opens": dom[-1]["opens"] if dom else None,
                   "page_errors": Counter(p["text"][:120] for p in probe if p.get("kind") in ("pageerror", "console")).most_common(8),
                   "crashes": sum(1 for p in probe if p.get("kind") == "crash")}
    # Drift: one full state a minute; latency, and what the radio picture holds in an empty room
    samples = [m for m in mon if m["kind"] == "sample"]
    def picture(m):
        st = m["state"]
        drops = [abs(x["drop_db"]) for x in st["links"] if x.get("drop_db") is not None]
        static = max(st["xray"]["static_db"]) if st.get("xray") else None
        return {"min": round((m["t"] - summ["start"]) / 60), "lag_ms": m["lag_ms"],
                "path": next((g["path"] for g in segs if g["start"] <= m["t"] <= g["end"] and not g["training"]), None),
                "mean_abs_drop_db": round(statistics.fmean(drops), 2) if drops else None,
                "max_static_db": None if static is None else round(static, 2), "objects": len(st["objects"])}
    pics = [picture(m) for m in samples]
    empty = [p for p in pics if p["path"] == "empty_room" and p["mean_abs_drop_db"] is not None]
    r["drift"] = {"lag_ms_first_last": [pics[0]["lag_ms"], pics[-1]["lag_ms"]] if pics else None,
                  "lag_ms_max": max((p["lag_ms"] for p in pics), default=None), "empty_room": empty}
    narr = [m for m in mon if m["kind"] == "trans" and m["what"] == "narration" and m["to"]]
    r["narrations"] = len(narr)
    json.dump(r, open(run / "report.json", "w"), indent=1, default=str)
    print(json.dumps(r, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
