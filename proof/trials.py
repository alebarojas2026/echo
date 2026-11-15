"""Score operator-confirmed crowd, tamper and live-lesson recordings."""
import argparse
import json
import math
from pathlib import Path
from statistics import median
import subprocess

from proof.security import covered, healthy, interval, overlap, spans
from proof.score import cluster_interval, load_session
from proof.provenance import prepare_update, require_board, empty_proof


def read(path):
    return [] if str(path) == "-" else [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def record(row, output, clock):
    if row.get("v") == 2 and row.get("type") in {"state", "event"}:
        row = dict(row, recv_t=int(clock()*1000))
        output.write(json.dumps(row, allow_nan=False)+"\n")
        output.flush()
        return row


def analyze(recordings, layout):
    ids = [s["meta"]["session"] for s, _, _ in recordings]
    if len(ids) != len(set(ids)): raise ValueError("duplicate session")
    zones = {z["id"]: z.get("still_alert_s") for z in layout["zones"]}
    nodes = {n["id"] for n in layout["nodes"]}
    passes = affected = crowd_events = still = alerts = unplugs = caught = false = correct = total = 0
    crowd_ms = clean_ms = 0
    lessons = []
    walk_counts = []
    for session, capture, annotations in recordings:
        identity, purpose = session["meta"]["session"], session["meta"].get("purpose")
        start = session["meta"]["recv_t"]
        for row in capture + annotations:
            if row.get("v") != 2 or type(row.get("recv_t")) not in (int, float) or not math.isfinite(row["recv_t"]):
                raise ValueError("capture/annotations need finite board recv_t and v2")
        for a in annotations:
            if a.get("session") != identity or type(a.get("end_t")) not in (int,float) or not math.isfinite(a["end_t"]) \
                    or not start <= a["recv_t"] < a["end_t"]:
                raise ValueError("annotation needs matching session and a positive interval after start")
            if a["kind"] in {"still", "walk"} and a.get("zone") not in zones: raise ValueError("unknown zone")
            if a["kind"] == "unplug" and a.get("node") not in nodes: raise ValueError("unknown node")
        # Repeated/overlapping annotations must never multiply trials or exposure.
        for kind in {a["kind"] for a in annotations}:
            group = sorted((a for a in annotations if a["kind"] == kind), key=lambda a:a["recv_t"])
            if any(a["end_t"] > b["recv_t"] for a,b in zip(group,group[1:])): raise ValueError("overlapping annotations")
        states = sorted((r.get("state", r) | {"recv_t":r["recv_t"]} for r in capture
                         if r.get("state", r).get("type") == "state" and r["recv_t"] >= start), key=lambda s:s["recv_t"])
        events = {}
        for e in capture:
            if e.get("type") != "event" or e.get("kind") not in {"intrusion", "tamper", "alert_on"}: continue
            if not e.get("id"): raise ValueError("events need ids")
            events.setdefault(e["id"], e)
        observed = spans(states, lambda s:s.get("armed") is True and s.get("health",{}).get("status") in {"ok","degraded","blind"}, 1000)
        good = spans(states, lambda s:s.get("armed") is True and healthy(s), 1000)
        selected = lambda kind: [a for a in annotations if a["kind"] == kind]
        def hits(kind, a, end=None):
            return [e for e in events.values() if e["kind"] == kind and a["recv_t"] <= e["recv_t"]
                    and (e["recv_t"] < a["end_t"] if end is None else e["recv_t"] <= end)
                    and (kind != "tamper" or e.get("info",{}).get("node") == a.get("node"))]
        if purpose == "crowd":
            crowd = [(a["recv_t"],a["end_t"],a) for a in selected("crowd")]
            exposure = overlap(crowd, good)
            crowd_ms += sum(b-a for a,b,_ in exposure)
            crowd_events += sum(e["kind"] == "intrusion" and any(a<=e["recv_t"]<b for a,b,_ in exposure) for e in events.values())
            for a in selected("pass"):
                if covered(exposure,a["recv_t"],a["end_t"]):
                    passes += 1
                    affected += bool(hits("intrusion",a))
            for a in selected("still"):
                limit = zones[a["zone"]]
                if limit is not None and a["end_t"]-a["recv_t"] >= (limit+5)*1000 and covered(good,a["recv_t"],a["end_t"]):
                    still += 1
                    alerts += any(e["kind"] == "alert_on" and a["recv_t"]+limit*1000 <= e["recv_t"] < a["end_t"]
                                  and e.get("info",{}).get("zone") == a["zone"] for e in events.values())
        if purpose == "heldout":
            old_correct, old_total = correct, total
            used = set()
            for a in selected("unplug"):
                if a["end_t"] >= a["recv_t"]+5000 and covered(observed,a["recv_t"],a["recv_t"]+5000):
                    unplugs += 1
                    matches = [e for e in hits("tamper",a,a["recv_t"]+5000) if e["id"] not in used]
                    if matches:
                        caught += 1
                        used.add(matches[0]["id"])
            # Split captured armed exposure at trial edges; unplug/recovery time is excluded.
            for a in selected("tamper"):
                edges = {a["recv_t"],a["end_t"]}
                for u in selected("unplug"):
                    edges.update(t for t in (u["recv_t"],u["end_t"]) if a["recv_t"]<t<a["end_t"])
                edges = sorted(edges)
                clean = [(x,y,a) for x,y in zip(edges,edges[1:]) if not any(u["recv_t"]<=x<u["end_t"] for u in selected("unplug"))]
                clean = overlap(clean,observed)
                clean_ms += sum(y-x for x,y,_ in clean)
                false += sum(e["kind"] == "tamper" and any(x<=e["recv_t"]<y for x,y,_ in clean) for e in events.values())
            off = spans(states, lambda s:s.get("cam") == "off" and healthy(s) and (s.get("model") or {}).get("trained") is True
                        and identity not in (s.get("model") or {}).get("train_sessions",[]), 1000)
            for a in selected("walk"):
                if not covered(off,a["recv_t"],a["end_t"]): continue
                seen = set()
                for s in states:
                    bucket = int(s["recv_t"]//200)
                    if a["recv_t"]<=s["recv_t"]<a["end_t"] and bucket not in seen:
                        seen.add(bucket)
                        total += 1
                        correct += s["pred"].get("zone") == a["zone"]
            if total > old_total: walk_counts.append((correct-old_correct,total-old_total))
        if purpose == "train":
            ready = None
            captured = spans(states,lambda s:True,1000)
            for s in states:
                model = s.get("model") or {}
                training = model.get("training") or {}
                lesson = training.get("lesson") or {}
                if model.get("trained") is True and identity in training.get("sessions",[]) and lesson.get("started_t",-1)>=start \
                        and lesson.get("fits",0)>=1 and lesson.get("of")==10 and lesson.get("agree",0)>=8 and healthy(s) \
                        and states[0]["recv_t"]-start <= 1000 and covered(captured,states[0]["recv_t"],s["recv_t"]):
                    ready = (s["recv_t"]-start)/1000
                    break
            lessons.append({"session":identity,"ready_s":ready})
    times = [r["ready_s"] for r in lessons if r["ready_s"] is not None]
    return {"passers_by":{"trials":passes or None,"false_intrusions":affected if passes else None,"ci95":interval(affected,passes),
                           "intrusion_events":crowd_events if crowd_ms else None,"duration_s":crowd_ms/1000 or None,
                           "intrusions_per_hour":crowd_events*3600000/crowd_ms if crowd_ms else None,
                           "still_trials":still or None,"still_alerts":alerts if still else None,"still_ci95":interval(alerts,still)},
            "tamper":{"unplugs":unplugs or None,"detected":caught if unplugs else None,"ci95":interval(caught,unplugs),"within_s":5,
                      "false_events":false if clean_ms else None,"duration_s":clean_ms/1000 or None,"false_per_hour":false*3600000/clean_ms if clean_ms else None},
            "lesson":{"sessions":lessons,"shortest_s":min(times) if times else None,"longest_s":max(times) if times else None,
                      "median_s":median(times) if times else None,"unplugged_walk":{"correct":correct if total else None,"total":total or None,"ci95":cluster_interval(walk_counts)}}}


def publish(proof, report, recordings, commit, schema):
    if "security_trials" not in schema.get("properties",{}): raise ValueError("security_trials schema pending #556")
    for session, capture, annotations in recordings:
        if any(r.get("state",r).get("src") != "live" for r in session["messages"]+capture+annotations):
            raise ValueError("synthetic/replay evidence cannot populate proof")
    from contracts.check import VALIDATORS
    out = prepare_update(proof,commit)
    previous = proof.get("security_trials") or {}
    blocks = {}
    for key, value in report.items():
        has_data = any(v is not None for k,v in value.items() if k not in {"within_s","sessions","unplugged_walk"})
        if key == "lesson": has_data = bool(value["sessions"]) or value["unplugged_walk"]["total"] is not None
        blocks[key] = value if has_data else previous.get(key,value)
    out["security_trials"] = blocks
    VALIDATORS["proof"].evolve(schema=schema).validate(out)
    return out


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record",nargs=3,action="append",default=[],metavar=("SESSION","STATES","TRIALS"))
    parser.add_argument("--nodes",type=Path,default=root/"radio/nodes.json")
    parser.add_argument("--proof",type=Path)
    args = parser.parse_args()
    recordings = [(load_session(s),read(c),read(a)) for s,c,a in args.record]
    report = analyze(recordings,json.loads(args.nodes.read_text()))
    if args.proof:
        require_board()
        schema = json.loads((root/"contracts/schemas/proof.json").read_text())
        commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        current = json.loads(args.proof.read_text()) if args.proof.exists() else empty_proof()
        out = publish(current,report,recordings,commit,schema)
        args.proof.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"diagnostic":not bool(args.proof),"security_trials":report},indent=2,allow_nan=False))


if __name__ == "__main__": main()
