"""Entry detection and false-presence/intrusion rates from independent recordings."""
import argparse
import json
from pathlib import Path
import math
import subprocess

from proof.provenance import prepare_update
from proof.score import load_session


def spans(rows, valid, gap):
    rows = sorted(rows, key=lambda r: r["recv_t"])
    return [(a["recv_t"], b["recv_t"], a) for a, b in zip(rows, rows[1:])
            if valid(a) and valid(b) and 0 < b["recv_t"]-a["recv_t"] <= gap]


def covered(rows, start, end):
    cursor = start
    for a, b, _ in rows:
        if b <= cursor: continue
        if a > cursor: return False
        cursor = b
        if cursor >= end: return True
    return False


def overlap(left, right):
    out, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        a, b, _ = left[i]
        c, d, row = right[j]
        if max(a, c) < min(b, d): out.append((max(a, c), min(b, d), row))
        if b <= d: i += 1
        else: j += 1
    return out


def interval(correct, total):
    if not total: return None
    z, p = 1.959963984540054, correct/total
    centre = (p+z*z/(2*total))/(1+z*z/total)
    radius = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [max(0, centre-radius), min(1, centre+radius)]


def valid_label(row):
    return (row.get("type") == "label" and row.get("clipped") is False and row.get("mode") in {"person","off"}
            and type(row.get("present")) is bool and row.get("persons_in_frame") in {0,1}
            and isinstance(row.get("zone"), int) and (row["zone"]>0 if row["present"] else row["zone"]==0))


def healthy(row):
    return row.get("health", {}).get("status") in {"ok", "degraded"} and row.get("pred") is not None


def hold_seconds(layout):
    armed = layout.get("armed")
    if armed is not None and not isinstance(armed,dict): raise ValueError("armed must be a configuration object")
    value = (armed or {}).get("hold_s", 3)
    if value is None: value = 3
    if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
        raise ValueError("armed.hold_s must be a finite nonnegative number")
    return value


def analyze(pairs, layout=None):
    hold = hold_seconds(layout or {})
    deadline_ms = (hold+2)*1000
    ids = [session["meta"]["session"] for session,_ in pairs]
    if len(ids)!=len(set(ids)): raise ValueError("duplicate evaluation session")
    entries = detected = armed_entries = intrusions = presence_false = intrusion_false = 0
    duration = armed_duration = passed_duration = passed_by = 0
    for session, capture in pairs:
        if session["meta"].get("purpose") != "heldout": raise ValueError("security evaluation needs heldout sessions")
        labels = sorted((m for m in session["messages"] if m.get("type") == "label"), key=lambda m:m["recv_t"])
        states = sorted((m.get("state", m) | {"recv_t":m["recv_t"]} for m in capture if m.get("state", m).get("type") == "state"), key=lambda m:m["recv_t"])
        events = sorted((m for m in capture if m.get("type") == "event"),key=lambda m:m["recv_t"])
        truth = spans(labels, valid_label, 500)
        occupied = [span for span in truth if span[2]["present"]]
        observed = spans(states, lambda s:"pred" in s and s.get("health",{}).get("status") in {"ok","degraded","blind"}, 1000)
        armed = spans(states, lambda s:s.get("armed") is True, 1000)
        active_armed = overlap(observed,armed)
        passed_duration += sum(b-a for a,b,_ in active_armed)/1000
        used = set()
        for before, after in zip(labels, labels[1:]):
            t = after["recv_t"]
            if not (valid_label(before) and valid_label(after) and not before.get("present") and after.get("present")
                    and 0 < t-before["recv_t"] <= 500 and covered(truth, t, t+2000) and covered(observed, t, t+2000)):
                continue
            entries += 1
            detected += any(t <= s["recv_t"] <= t+2000 and healthy(s) and s["pred"].get("present")
                            and s["pred"].get("kind") == "person" for s in states)
            if (covered(occupied,t,t+hold*1000) and covered(truth,t,t+deadline_ms)
                    and covered(observed,t,t+deadline_ms) and covered(armed,t,t+deadline_ms)):
                armed_entries += 1
                hits = [e for e in events if e.get("kind") == "intrusion" and e.get("id") not in used and t <= e["recv_t"] <= t+deadline_ms]
                if hits:
                    if not hits[0].get("id"): raise ValueError("intrusion events need ids")
                    used.add(hits[0]["id"])
                    intrusions += 1
        empty = [s for s in truth if not s[2].get("present")]
        negative = overlap(empty, spans(states, healthy, 1000))
        armed_negative = overlap(negative, armed)
        duration += sum(b-a for a,b,_ in negative)/1000
        armed_duration += sum(b-a for a,b,_ in armed_negative)/1000
        seen = set()
        for event in events:
            kind, t = event.get("kind"), event["recv_t"]
            if kind not in {"enter", "intrusion", "passed_by"}: continue
            if kind == "intrusion" and event.get("id") in used: continue
            eligible = active_armed if kind == "passed_by" else negative if kind == "enter" else armed_negative
            if not any(a <= t < b for a,b,_ in eligible): continue
            if not event.get("id"): raise ValueError("captured events need ids")
            if event["id"] in seen: continue
            seen.add(event["id"])
            presence_false += kind == "enter"
            intrusion_false += kind == "intrusion"
            passed_by += kind == "passed_by"
    return {"detection":{"entries":entries or None,"detected":detected if entries else None,"ci95":interval(detected,entries),
                         "armed_entries":armed_entries or None,"intrusions":intrusions if armed_entries else None,
                         "intrusion_ci95":interval(intrusions,armed_entries),"within_s":hold+2,"hold_s":hold},
            "false_alarms":{"presence_events":presence_false if duration else None,"intrusions":intrusion_false if armed_duration else None,
                            "duration_s":duration or None,"armed_duration_s":armed_duration or None,
                            "presence_per_hour":presence_false*3600/duration if duration else None,
                            "intrusions_per_hour":intrusion_false*3600/armed_duration if armed_duration else None,
                            "passed_by_events":passed_by if passed_duration else None,"passed_by_duration_s":passed_duration or None,
                            "passed_by_per_hour":passed_by*3600/passed_duration if passed_duration else None}}


def publish(proof, report, pairs, commit, schema):
    if "security" not in schema.get("properties", {}): raise ValueError("security proof schema is pending contract issue #453")
    for session, capture in pairs:
        if any(m.get("src") != "live" for m in session["messages"]): raise ValueError("synthetic/replay sessions cannot populate proof")
        if any(m.get("state",m).get("src") != "live" for m in capture): raise ValueError("synthetic capture cannot populate proof")
    from contracts.check import VALIDATORS
    from copy import deepcopy
    out = prepare_update(proof, commit)
    existing = deepcopy(proof.get("security") or report)
    for key in ("detection","false_alarms","fewer_devices"):
        if key == "false_alarms":
            alarms = existing.setdefault(key,{})
            for exposure, fields in [("duration_s",("presence_events","intrusions","duration_s","armed_duration_s","presence_per_hour","intrusions_per_hour")),
                                     ("passed_by_duration_s",("passed_by_events","passed_by_duration_s","passed_by_per_hour"))]:
                if report[key].get(exposure) is not None:
                    alarms.update({field:report[key][field] for field in fields})
            for field,value in report[key].items(): alarms.setdefault(field,value)
            continue
        has_data = (report[key].get("entries") is not None if key=="detection" else
                    any(row["zone"]["total"] is not None for row in report[key]))
        if has_data: existing[key] = report[key]
    out["security"] = existing
    VALIDATORS["proof"].evolve(schema=schema).validate(out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", nargs=2, action="append", default=[], metavar=("SESSION", "CAPTURE"))
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--train", nargs="*", type=Path, default=[])
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--allow-sim", action="store_true", help="diagnostics only; incompatible with --proof")
    parser.add_argument("--nodes", type=Path, default=Path(__file__).resolve().parents[1]/"radio/nodes.json")
    args = parser.parse_args()
    if args.allow_sim and args.proof: parser.error("synthetic diagnostics cannot update proof")
    pairs = [(load_session(a), [json.loads(l) for l in Path(b).read_text().splitlines() if l.strip()]) for a,b in args.pair]
    layout = json.loads(args.nodes.read_text())
    report = analyze(pairs,layout)
    report["fewer_devices"] = []
    if args.train:
        from proof.ablation import compare
        from proof.score import read_baseline
        if args.baseline is None: parser.error("--train requires --baseline for subset replay")
        report["fewer_devices"] = compare([load_session(p) for p in args.train], [s for s,_ in pairs],
                                           read_baseline(args.baseline)[0], layout, args.allow_sim)
    if args.proof:
        from proof.provenance import require_board
        require_board()
        schema = json.loads((Path(__file__).resolve().parents[1]/"contracts/schemas/proof.json").read_text())
        current = json.loads(args.proof.read_text())
        commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        out = publish(current,report,pairs,commit,schema)
        args.proof.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"diagnostic":not bool(args.proof),"security":report},indent=2,allow_nan=False))


if __name__ == "__main__": main()
