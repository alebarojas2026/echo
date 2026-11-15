"""Score held-out camera-off cycles against an independent enter/leave CSV."""
import argparse
from bisect import bisect_right
from collections import Counter
import csv
import json
import math
from pathlib import Path
import subprocess

from proof.score import load_session, presence_from_confusion, training_walkers, walker_id, validate_report
from proof.provenance import prepare_update, require_board, empty_proof
from proof import layout as L


def read_log(path):
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["recv_t","present"]: raise ValueError("CSV header must be recv_t,present")
        rows = list(reader)
    out = []
    for row in rows:
        if set(row)!={"recv_t","present"} or None in row.values(): raise ValueError("invalid truth columns")
        t = float(row["recv_t"])
        if not math.isfinite(t) or t<0 or row["present"] not in {"0","1"}: raise ValueError("invalid truth row")
        out.append((t,row["present"] == "1"))
    if len(out)<3 or len(out)%2 != 1 or any(p != bool(i%2) for i,(_,p) in enumerate(out)):
        raise ValueError("log must contain complete empty/occupied cycles ending empty")
    if any(b[0]-a[0]<60000 for a,b in zip(out,out[1:])): raise ValueError("each phase needs at least 60 seconds and increasing board time")
    return out


def score_cycles(session, capture, log, training, allow_sim=False, layout=None):
    # On a layout with a presence line the brain decides with no model: its own decisions are scored as they are.
    line = L.presence_line(layout or L.load())
    meta = session["meta"]
    if meta.get("purpose") != "heldout": raise ValueError("presence needs a predeclared heldout session")
    if any(s["meta"].get("purpose") not in {"train","object"} for s in training): raise ValueError("invalid training purpose")
    ids = [s["meta"]["session"] for s in training]
    if len(ids)!=len(set(ids)) or meta["session"] in ids: raise ValueError("training/heldout session leakage")
    walker = walker_id(meta.get("walker"),"held-out cycles")
    if not training and not line: raise ValueError("original training provenance is required")
    sources = session["messages"] + capture + [m for s in training for m in s["messages"]]
    if not allow_sim and any(r.get("state",r).get("src")!="live" for r in sources):
        raise ValueError("synthetic inputs cannot populate measured presence")
    if log[0][0] < meta["recv_t"]: raise ValueError("truth precedes its session: use the same board clock")
    states = []
    for r in capture:
        s = r.get("state",r)
        if s.get("type") != "state": continue
        if s.get("v") != 2 or type(r.get("recv_t")) not in (int,float) or not math.isfinite(r["recv_t"]):
            raise ValueError("capture needs v2 and finite board recv_t")
        states.append(dict(s,recv_t=r["recv_t"]))
    if states and log[-1][0] > max(s["recv_t"] for s in states)+1000: raise ValueError("truth extends beyond the capture")
    starts = [t for t,_ in log]
    counts, seen, versions = Counter(), set(), set()
    for s in sorted(states,key=lambda s:s["recv_t"]):
        t = s["recv_t"]
        if not starts[0] <= t < starts[-1]: continue
        model = s.get("model") or {}
        fitted = model.get("train_sessions")
        if line and model.get("trained") is not True:
            if s.get("cam") in {"on","stalled"}: raise ValueError("no camera may run during the cycles")
            fitted = []
        elif s.get("cam") != "off": raise ValueError("camera must remain off throughout independent cycles")
        elif model.get("trained") is not True or not isinstance(fitted,list) or not fitted or not model.get("ver"):
            raise ValueError("cycle evaluation requires a trained model with known provenance")
        if not set(fitted)<=set(ids): raise ValueError("missing metadata for model training sessions")
        if not versions and walker in training_walkers([s for s in training if s["meta"]["session"] in fitted]):
            raise ValueError("training/held-out walker leakage")
        versions.add((model.get("ver") if fitted else None,tuple(sorted(fitted))))
        if len(versions)>1: raise ValueError("model changed during held-out cycles")
        pred = s.get("pred") or {}
        bucket = int((t-starts[0])//1000)
        if starts[0]+(bucket+1)*1000 > starts[-1] or bucket in seen: continue
        if s.get("health",{}).get("status") not in {"ok","degraded"} or type(pred.get("present")) is not bool: continue
        seen.add(bucket)
        actual = log[bisect_right(starts,t)-1][1]
        counts[(int(actual),int(pred["present"]))] += 1
    matrix = [[counts[(a,p)] for p in (0,1)] for a in (0,1)]
    if line and versions <= {(None,())}:
        return presence_from_confusion({"classes":[0,1],"counts":matrix},(len(log)-1)//2,("SYNTHETIC SELF-TEST; " if allow_sim else "")
                                       + f"the line {line} decides, no model and no lesson; no camera; 1 Hz states against written enter/leave log; see proof/PRESENCE.md")
    method = ("SYNTHETIC SELF-TEST; " if allow_sim else "") + "walker-independent; camera off; 1 Hz states against written enter/leave log; see proof/PRESENCE.md"
    return presence_from_confusion({"classes":[0,1],"counts":matrix},(len(log)-1)//2,method)


def publish(proof, result, commit, schema):
    if "synthetic" in result["method"].lower(): raise ValueError("synthetic presence cannot populate proof")
    if "presence" not in schema.get("properties",{}): raise ValueError("presence schema is pending #656")
    if result["total"] is None: return dict(proof)
    out = prepare_update(proof,commit)
    out["presence"] = result
    validate_report(out,schema)
    return out


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session",type=Path)
    parser.add_argument("states",type=Path)
    parser.add_argument("log",type=Path)
    parser.add_argument("--more-record",nargs=3,type=Path,action="append",default=[])
    parser.add_argument("--train",nargs="+",type=Path,default=[],help="not needed on a layout with a presence line")
    parser.add_argument("--proof",type=Path)
    parser.add_argument("--allow-sim",action="store_true")
    args = parser.parse_args()
    if args.allow_sim and args.proof: parser.error("synthetic diagnostics cannot write proof")
    if not args.train and not L.presence_line(L.load()): parser.error("--train is required on a layout with no presence line")
    training, results, seen = [load_session(p) for p in args.train], [], set()
    for s,c,l in [(args.session,args.states,args.log)]+args.more_record:
        session = load_session(s)
        if session["meta"]["session"] in seen: raise ValueError("duplicate cycle session")
        seen.add(session["meta"]["session"])
        capture = [json.loads(line) for line in c.read_text().splitlines() if line.strip()]
        results.append(score_cycles(session,capture,read_log(l),training,args.allow_sim))
    result = dict(results[0])
    for key in ("correct","total","always_empty_correct","cycles"):
        values = [r[key] for r in results if r["total"] is not None]
        result[key] = sum(values) if values else None
    result["method"] += f"; {len(results)} recorded sessions"
    if args.proof:
        require_board()
        schema = json.loads((root/"contracts/schemas/proof.json").read_text())
        commit = subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
        current = json.loads(args.proof.read_text()) if args.proof.exists() else empty_proof()
        out = publish(current,result,commit,schema)
        args.proof.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"presence":result,"diagnostic":not bool(args.proof)},indent=2,allow_nan=False))


if __name__ == "__main__": main()
