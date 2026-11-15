"""Recordings taken on the kit, played through the brain, scored against the operator's index.

    python -m proof.replayed <folder> <plan.json> --layout radio/layouts/gate.json --output proof/proof.replay.json
    python -m proof.render_table --replay proof/proof.replay.json --output PROOF.md

For one spot with a presence line (CONTRACTS.md section 6), where the line alone decides and no
model exists. The readings are real (`src: live`, as the bus wrote them); the decisions are the
brain's own (brain.core.Brain, nothing of its rules is written again here); the truth is the
operator's index of what each short recording was. See proof/REPLAYED.md.

The wall between tuning and reporting is in the plan: every session is "tuning" or "report", set
before any setting was chosen. Tuning sessions are played, because the brain has to live through
the sitting in order, and are never scored. Only report sessions give numbers.

What this is not: live on the kit. Each recording is all-empty or all-person and the seconds
between them were not recorded, so they are joined end to end. Every row made from this says
"replayed through the brain from recordings taken on the kit".
"""
import argparse
import hashlib
import json
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from proof.shuffled import PRESENT_MS, coverage, exact_interval, plain_range, present_runs

STATE_EVERY_MS = 100     # the live loop takes state about 10 times a second
JOIN_MS = 40             # the next recording starts this long after the last reading of the one before
RELEASE_MAX_MS = 2000    # after a person's recording, "somebody" past this long is a false presence, not a slow let-go
MOTION_SKIP_MS = 3000    # moving / still is scored from here: until then the 2 s spread still holds the join
THERE = ("person", "still", "moving")
KINDS = ("baseline", "empty") + THERE + ("walk", "side", "behind", "thing")
SCORED = ("empty",) + THERE
WORDS = "one person, one night, replayed through the brain from recordings taken on the kit"
METHOD = "live recordings joined end to end and played through brain.core.Brain with no model; operator index as truth; report sessions only"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def readings(path):
    """(recv_t, link, dbm) of one live session file, oldest first. Anything not live is refused."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if sum(r.get("type") == "meta" for r in rows) != 1:
        raise ValueError(f"{path.name}: exactly one session meta is required")
    if any(r.get("src") != "live" for r in rows):
        raise ValueError(f"{path.name}: only live recordings are measured input")
    out = [(r["recv_t"], r["link"], float(r["dbm"])) for r in rows if r.get("type") == "rssi"
           and isinstance(r.get("recv_t"), (int, float)) and math.isfinite(r["recv_t"])]
    if not out:
        raise ValueError(f"{path.name}: no readings")
    return sorted(out, key=lambda r: r[0])


def load(folder, plan):
    """The plan's runs, read and joined end to end. A run with nothing to report is refused."""
    if plan.get("truth") != "operator" or not isinstance(plan.get("people"), int) or not plan.get("night"):
        raise ValueError("the plan needs truth: operator, people and night")
    if not isinstance(plan.get("recorded_commit"), str) or len(plan["recorded_commit"]) != 40:
        raise ValueError("the plan needs the full commit the board ran while recording")
    folder, runs, seen = Path(folder), [], set()
    for run in plan["runs"]:
        for s in run["sessions"]:
            if s.get("is") not in KINDS or s.get("role") not in ("tuning", "report"):
                raise ValueError(f"{s.get('session')}: is one of {', '.join(KINDS)}; role is tuning or report")
            if s["role"] == "report" and s["is"] not in SCORED + ("baseline",):
                raise ValueError(f"{s['session']}: no scorer for a report {s['is']} recording")
            if s["session"] in seen:
                raise ValueError(f"{s['session']}: listed twice")
            seen.add(s["session"])
        first = run["sessions"][0]
        if first["is"] != "baseline" and not run.get("baseline_s"):
            raise ValueError(f"run {run['id']}: the first session is the baseline, or the run names baseline_s")
        if not any(s["role"] == "report" and s["is"] != "baseline" for s in run["sessions"]):
            raise ValueError(f"run {run['id']}: nothing to report; a tuning run is never scored here")
        out = {"id": run["id"], "placement": run.get("placement") or run["id"], "limit": run.get("limit"),
               "base": [], "readings": [], "parts": []}
        cursor = 0
        for i, s in enumerate(run["sessions"]):
            path = folder / f"{s['session']}.jsonl"
            raw = readings(path)
            shift = cursor - raw[0][0]
            rows = [(t + shift, link, dbm) for t, link, dbm in raw]
            start, cursor = rows[0][0], rows[-1][0] + JOIN_MS
            if i == 0:
                cut = start + int(run["baseline_s"] * 1000) if s["is"] != "baseline" else cursor
                out["base"] = [r for r in rows if r[0] < cut]
                start = cut if s["is"] != "baseline" else start
            out["readings"] += rows
            out["parts"].append({"session": s["session"], "is": s["is"], "role": s["role"], "start": start,
                                 "end": cursor, "sha256": digest(path), "last_t": raw[-1][0]})
        runs.append(out)
    return runs


def baseline_doc(base, links):
    """baseline.json as the brain writes it, from the readings of an empty stretch."""
    from brain import features as F
    msgs = [{"type": "rssi", "recv_t": t, "link": link, "dbm": dbm} for t, link, dbm in base if link in links]
    if not msgs:
        raise ValueError("the baseline has no readings of this layout's lines")
    level, quiet, count = F.baseline(msgs), F.quiet(msgs), {}
    for m in msgs:
        count[m["link"]] = count.get(m["link"], 0) + 1
    seconds = max((msgs[-1]["recv_t"] - msgs[0]["recv_t"]) / 1000, 1.0)
    return {"t": msgs[-1]["recv_t"], "session": None,
            "links": {k: {"base_dbm": level[k], "expected_hz": round(count[k] / seconds, 1),
                          **({"quiet_db": round(quiet[k], 2)} if k in quiet else {})} for k in level}}


def play(run, layout):
    """One run through a new, armed brain with no model. States ten times a second, and the events."""
    from brain import settings as S
    from brain.core import Brain
    if not (layout.get("presence") or {}).get("line"):
        raise ValueError("this layout names no presence line: the replay has nothing to decide with and no model")
    with tempfile.TemporaryDirectory() as folder:
        doc = baseline_doc(run["base"], {link["id"] for link in layout["links"]})
        (Path(folder) / "baseline.json").write_text(json.dumps(doc), encoding="utf-8")
        brain = Brain(clock=None, sessions_dir=folder, settings=S.DEFAULT, nodes=layout)
        if not brain.base or brain.model is not None:
            raise ValueError("the brain did not start cold on this baseline")
        brain.on_cmd({"v": 2, "type": "cmd", "cmd": "arm", "args": {"on": True}})
        brain.pop_events()
        states, events, next_state = [], [], None
        for t, link, dbm in run["readings"]:
            brain.on_message({"v": 2, "type": "rssi", "src": "live", "t": t, "recv_t": t, "link": link, "dbm": dbm})
            if next_state is None or t >= next_state:
                next_state = t + STATE_EVERY_MS if next_state is None or t - next_state >= STATE_EVERY_MS \
                    else next_state + STATE_EVERY_MS
                pred = brain.state()["pred"]
                events += [{"t": t, "kind": e["kind"]} for e in brain.pop_events()]
                states.append({"t": t, "hidden": pred is None, "present": bool(pred and pred["present"]),
                               "motion": pred and pred.get("motion"), "kind": pred and pred.get("kind")})
        line = layout["presence"]["line"]
        return states, events, round(brain.base[line] - doc["links"][line]["base_dbm"], 2)


def score(run, states, events):
    """Counts for the report sessions of one played run. Tuning sessions are not looked at."""
    step = STATE_EVERY_MS / 1000
    out = {"id": run["id"], "placement": run["placement"], "limit": run["limit"],
           "stands": {"n": 0, "found": 0}, "decide_s": [], "release_s": [], "dropouts": 0,
           "empty": {"sessions": 0, "seconds": 0.0, "false_presences": 0, "false_present_s": 0.0, "enters": 0,
                     "intrusions": 0, "passed_by": 0},
           "hidden_s": 0.0, "object_s": 0.0, "blind_events": 0,
           "still": {"sessions": 0, "n": 0, "right": 0}, "moving": {"sessions": 0, "n": 0, "right": 0}}
    for i, part in enumerate(run["parts"]):
        if part["role"] != "report" or part["is"] == "baseline":
            continue
        a, b, kind = part["start"], part["end"], part["is"]
        mine = [s for s in states if a <= s["t"] < b]
        before = run["parts"][i - 1]["is"] if i else None
        out["hidden_s"] += sum(s["hidden"] for s in mine) * step
        out["object_s"] += sum(s["kind"] == "object" for s in mine) * step
        out["blind_events"] += sum(e["kind"] == "blind_on" and a <= e["t"] < b for e in events)
        if kind == "empty":
            free = a
            if before in THERE:   # the person of the recording before has to be let go first
                gone = next((s["t"] for s in mine if not s["hidden"] and not s["present"]), None)
                free = min(a + RELEASE_MAX_MS, b if gone is None else gone)
                out["release_s"].append(None if gone is None else round((gone - a) / 1000, 2))
            empty = out["empty"]
            empty["sessions"] += 1
            empty["seconds"] += sum(y - x for x, y in coverage(states, free, b)) / 1000
            empty["false_presences"] += len(present_runs(states, free, b, minimum_ms=0))
            empty["false_present_s"] += sum(s["present"] and not s["hidden"] for s in mine if s["t"] >= free) * step
            for name, key in (("enter", "enters"), ("intrusion", "intrusions"), ("passed_by", "passed_by")):
                empty[key] += sum(e["kind"] == name and free <= e["t"] < b for e in events)
            continue
        runs = present_runs(states, a, b, minimum_ms=PRESENT_MS)
        if before not in THERE:   # a stand: somebody arrives on an empty spot
            out["stands"]["n"] += 1
            out["stands"]["found"] += bool(runs)
            if runs:
                out["decide_s"].append(round((runs[0] - a) / 1000, 2))
        after = [s for s in mine if runs and s["t"] >= runs[0] and not s["hidden"]]
        out["dropouts"] += sum(x["present"] and not y["present"] for x, y in zip(after, after[1:]))
        if kind in ("still", "moving"):
            there = [s for s in after if s["present"] and s["t"] >= a + MOTION_SKIP_MS]
            out[kind]["sessions"] += 1
            out[kind]["n"] += len(there)
            out[kind]["right"] += sum(s["motion"] == kind for s in there)
    for key in ("hidden_s", "object_s"):
        out[key] = round(out[key], 1)
    out["empty"]["seconds"] = round(out["empty"]["seconds"], 1)
    out["empty"]["false_present_s"] = round(out["empty"]["false_present_s"], 1)
    return out


def add(rows):
    """Several runs as one: counts add, lists join."""
    def merge(a, b):
        if isinstance(a, dict):
            return {k: merge(a[k], b[k]) for k in a}
        return a + b if isinstance(a, list) else round(a + b, 1) if isinstance(a, float) else a + b
    keep = [{k: v for k, v in r.items() if k not in ("id", "placement", "limit", "base_moved_db")} for r in rows]
    total = keep[0]
    for row in keep[1:]:
        total = merge(total, row)
    return total


def brain_build(root):
    """The last commit that touched the brain's code or a layout file: the build the decisions came from."""
    commit = subprocess.run(["git", "log", "-1", "--format=%H", "--", "brain", "radio/layouts"], cwd=root,
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "brain", "radio/layouts"], cwd=root,
                           capture_output=True, text=True).stdout.strip()
    if len(commit) != 40 or dirty:
        raise ValueError("the brain and the layout files must be a clean checkout of a known commit")
    return commit


def report(folder, plan, layout_path, root=None):
    layout_path = Path(layout_path)
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    runs, rows, sources, last = load(folder, plan), [], [], 0
    for run in runs:
        states, events, moved = play(run, layout)
        row = score(run, states, events)
        row["base_moved_db"] = moved
        rows.append(row)
        sources += [{k: p[k] for k in ("session", "role", "is", "sha256")} for p in run["parts"]]
        last = max([last] + [p["last_t"] for p in run["parts"] if p["role"] == "report"])
    counted = [r for r in rows if not r["limit"]]
    if not counted:
        raise ValueError("every run is a stated limit: nothing to report")
    listed = [s for run in plan["runs"] for s in run["sessions"]] + list(plan.get("tuning_only") or [])
    reported = {s["is"] for s in listed if s["role"] == "report"}
    once = {}
    for s in listed:
        if s["role"] == "tuning" and s["is"] not in reported and s["is"] != "baseline":
            once[s["is"]] = once.get(s["is"], 0) + 1
    return {"source": "live recordings, replayed", "method": METHOD, "words": WORDS, "people": plan["people"],
            "night": plan["night"], "recorded_commit": plan["recorded_commit"],
            "brain_commit": brain_build(root or Path(__file__).resolve().parents[1]),
            "layout": layout.get("layout"), "layout_sha256": digest(layout_path), "presence": layout["presence"],
            "armed": layout.get("armed"), "zones": len(layout["zones"]),
            "measured_at": datetime.fromtimestamp(last / 1000, timezone.utc).isoformat(),
            "replayed_at": datetime.now(timezone.utc).isoformat(),
            "runs": rows, "total": add(counted), "tuning_only": once, "sources": sources}


def rate_ceiling(events, minutes, level=0.95):
    """The exact (Poisson) upper end for a count over some minutes, per minute."""
    def cdf(mean):
        return sum(math.exp(-mean) * mean ** i / math.factorial(i) for i in range(events + 1))
    lo, hi = 0.0, events + 50.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > (1 - level) / 2 else (lo, mid)
    return hi / minutes


def spread(values):
    return f"{min(values):.2f} to {max(values):.2f} s (median {median(values):.2f} s)"


def sentences(result):
    """[(number, value, method, n)] in plain words: a count, its exact range, and what it rests on."""
    total, rows = result["total"], []
    people = "one person" if result["people"] == 1 else f"{result['people']} people"
    words = result["words"] if result["people"] == 1 else result["words"].replace("one person", people)
    stands = "; ".join(f"{r['stands']['n']} {r['placement']}" for r in result["runs"] if not r["limit"] and r["stands"]["n"])
    if total["stands"]["n"]:
        rows.append(("Presence found (10-second stands)", plain_range(total["stands"]["found"], total["stands"]["n"], "stands found"),
                     f"{words}. Found = the brain said somebody for 0.3 s in a row during the stand.",
                     f"{total['stands']['n']} stands ({stands})"))
    for r in result["runs"]:
        if not r["limit"] and len([x for x in result["runs"] if not x["limit"]]) > 1 and r["stands"]["n"]:
            rows.append((f"Found, {r['placement']}", plain_range(r["stands"]["found"], r["stands"]["n"], "stands found"),
                         f"{words}.", f"{r['stands']['n']} stands"))
    empty = total["empty"]
    if empty["seconds"]:
        minutes = empty["seconds"] / 60
        rows.append(("False presence per empty minute",
                     f"{empty['false_presences']} in {minutes:.1f} empty minutes ({empty['false_presences'] / minutes:.2g} a minute); "
                     f"with this little time the true rate is probably under {math.ceil(rate_ceiling(empty['false_presences'], minutes) * 10) / 10:.1f} a minute",
                     f"{words}. Every moment the brain said somebody on an empty spot counts, however short; armed throughout: "
                     f"{empty['intrusions']} intrusions, {empty['passed_by']} passed-by, {empty['enters']} arrivals said.",
                     f"{empty['sessions']} empty recordings, {minutes:.1f} minutes"))
    if total["decide_s"]:
        rows.append(("Time from the signal crossing to the decision", spread(total["decide_s"]),
                     f"{words}. From the first reading of a stand's recording to the brain saying somebody. The step-on itself "
                     "was not recorded as an event, so the time a body takes to step in is not in this number.",
                     f"{len(total['decide_s'])} stands"))
    for kind, label in (("still", "Standing still read as still"), ("moving", "Stepping about read as moving")):
        m = total[kind]
        if m["n"]:
            only = "one session: it shows it can work, not how often" if m["sessions"] == 1 else f"{m['sessions']} sessions"
            rows.append((label, f"{m['right']} of {m['n']} decisions ({only})",
                         f"{words}. Ten decisions a second from 3 s into the session; decisions inside one session are not independent trials.",
                         f"{m['sessions']} session"))
    for r in result["runs"]:
        if r["limit"] and r["stands"]["n"]:
            rows.append((f"Stated limit: {r['placement']}", plain_range(r["stands"]["found"], r["stands"]["n"], "stands found"),
                         f"{words}. {r['limit']}", f"{r['stands']['n']} stands"))
    return rows


def limits(result):
    names = {"walk": "walk-throughs", "side": "crossings to the side", "behind": "standing behind the device",
             "thing": "a thing left in the line"}
    out = [f"One spot (the layout has {result['zones']} zone and one line that decides), "
           f"{'one person' if result['people'] == 1 else str(result['people']) + ' people'}, one night, one room."]
    for r in result["runs"]:
        if r["limit"]:
            thing = f" The brain said \"object\" for {r['object_s']} s of those recordings." if r["object_s"] else ""
            out.append(f"{r['placement']}: {r['stands']['found']} of {r['stands']['n']} stands found. {r['limit']}{thing}")
    once = [names.get(k, k) for k in result["tuning_only"]]
    if once:
        out.append(f"{', '.join(once).capitalize()}: seen once, used for tuning, not a result.")
    out.append("Not live: each recording is all-empty or all-person and they are joined end to end, so no real step-on "
               "or step-off is in these numbers.")
    return out


def table(result):
    """The replayed rows for PROOF.md's generated block."""
    from proof.render_table import cell
    if result.get("method") != METHOD or result.get("source") != "live recordings, replayed":
        raise ValueError("only replays of live recordings are publishable")
    for key in ("recorded_commit", "brain_commit"):
        if not isinstance(result.get(key), str) or len(result[key]) != 40:
            raise ValueError("replay provenance is missing")
    date = datetime.fromisoformat(result["measured_at"]).date().isoformat() + " UTC"
    out = ["", "## Replayed from recordings taken on the kit", "",
           "| Number | Value | Method | N | Recorded | Brain build |", "|---|---|---|---|---|---|"]
    for row in sentences(result):
        out.append("| " + " | ".join(cell(c) for c in (*row, date, result["brain_commit"][:7])) + " |")
    p = result["presence"]
    out += ["", "Stated limits:", *[f"- {line}" for line in limits(result)], "",
            f"Recorded on the kit the night of {result['night']} (board build `{result['recorded_commit'][:7]}`); the last report "
            f"recording ended {result['measured_at']}. Played on {datetime.fromisoformat(result['replayed_at']).date().isoformat()} "
            f"through the brain of `{result['brain_commit']}` on the `{result['layout']}` layout (SHA256 `{result['layout_sha256']}`): "
            f"line `{p['line']}`, on {p.get('on_db')} dB, off {p.get('off_db')} dB, moving at {p.get('moving_spread_db')} dB of spread. "
            "The sessions were split into tuning and report before those settings were chosen; these rows use the report "
            f"sessions only ({sum(s['role'] == 'report' for s in result['sources'])} of {len(result['sources'])} recordings played). "
            "Ranges are exact (Clopper-Pearson for counts, Poisson for the rate), 95%, rounded outward. See proof/REPLAYED.md."]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--layout", type=Path, required=True, help="the layout file to play on; it must name a presence line")
    parser.add_argument("--output", type=Path, help="write the companion report here; omit to preview")
    args = parser.parse_args(argv)
    result = report(args.folder, json.loads(args.plan.read_text(encoding="utf-8")), args.layout)
    text = "\n".join(table(result))   # validate before replacing any existing report
    if args.output:
        args.output.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
