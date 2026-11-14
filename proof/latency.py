"""Timing from bus logs and capture-side timing records; never infer sample timing."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess

from proof.score import percentile


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def analyze(messages, states):
    readings = {m["recv_t"] for m in messages if m.get("v") == 2 and m.get("type") == "rssi"}
    decisions, end_to_end, seen = [], [], set()
    for record in sorted(states, key=lambda r: r["recv_t"]):
        state = record.get("state", record)
        if state.get("v") != 2 or state.get("type") != "state":
            continue
        # Capture-side metadata is outside the unchanged WebSocket state envelope.
        source_t = record.get("input_recv_t")
        if source_t not in readings or source_t in seen:
            continue
        elapsed = record["recv_t"] - source_t
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("capture and input timestamps must use the same board clock")
        seen.add(source_t)
        end_to_end.append(elapsed)
        duration = record.get("decision_ms")
        if duration is not None:
            if isinstance(duration, bool) or not math.isfinite(duration) or duration < 0 or duration > elapsed:
                raise ValueError("invalid per-decision timing span")
            decisions.append(duration)
    def summary(values):
        return {"p50": percentile(values, 0.5), "p95": percentile(values, 0.95)}
    return {"ms_per_decision": summary(decisions), "end_to_end_ms": summary(end_to_end),
            "decisions": len(decisions), "reflected_readings": len(end_to_end),
            "method": "first captured state explicitly attributed to input recv_t; no producer-clock joins"}


def update_proof(proof, result, messages, states, commit):
    if any(m.get("src") != "live" for m in messages):
        raise ValueError("synthetic or replay logs cannot populate measured proof")
    if any(r.get("state", r).get("src") != "live" for r in states):
        raise ValueError("synthetic state logs cannot populate measured proof")
    updated = dict(proof)
    updated["ms_per_decision"] = result["ms_per_decision"]
    updated["measured_at"] = datetime.now(timezone.utc).isoformat()
    updated["commit"] = commit
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("states", type=Path)
    parser.add_argument("--more-pairs", nargs=2, action="append", default=[], type=Path, metavar=("SESSION", "STATES"))
    parser.add_argument("--proof", type=Path, help="update this measured proof file; otherwise only report")
    args = parser.parse_args()
    messages, states = read_jsonl(args.session), read_jsonl(args.states)
    for session_path, state_path in args.more_pairs:
        messages.extend(read_jsonl(session_path))
        states.extend(read_jsonl(state_path))
    result = analyze(messages, states)
    if args.proof:
        proof = json.loads(args.proof.read_text())
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        args.proof.write_text(json.dumps(update_proof(proof, result, messages, states, commit), indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
