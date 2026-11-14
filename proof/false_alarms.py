"""False check-in, no-movement and object events against independent camera labels."""

import argparse
from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from proof.provenance import prepare_update, require_board


def load_zones():
    path = Path(__file__).resolve().parents[1] / "radio/nodes.json"
    return {z["id"]: z.get("still_alert_s") for z in json.loads(path.read_text())["zones"]}


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def intervals(messages):
    labels = sorted((m for m in messages if m.get("type") == "label"), key=lambda m: m["recv_t"])
    out, since, previous = [], None, None
    for a, b in zip(labels, labels[1:]):
        valid = (not a.get("clipped") and not b.get("clipped") and a.get("mode") != "object"
                 and b.get("mode") != "object" and 0 < b["recv_t"] - a["recv_t"] <= 500
                 and a.get("present") == b.get("present") and a.get("zone") == b.get("zone"))
        key = (a.get("present"), a.get("zone"))
        still = not a.get("present") or (a.get("motion") == b.get("motion") == "still")
        if not valid or not still:
            since, previous = None, None
            continue
        if key != previous or since is None:
            since = a["recv_t"]
        out.append((a["recv_t"], b["recv_t"], a, since))
        previous = key
    return out


def analyze(messages, events, zones=None):
    zones = load_zones() if zones is None else zones
    if not events:
        raise ValueError("missing events capture; absence of a capture is not zero events")
    if not messages:
        raise ValueError("missing session timestamps")
    session_start, session_end = min(m["recv_t"] for m in messages), max(m["recv_t"] for m in messages)
    capture_start, capture_end = min(m["recv_t"] for m in events), max(m["recv_t"] for m in events)
    if capture_start < session_start or capture_end > session_end:
        raise ValueError("events capture is outside the session recv_t range; check the board clock")
    spans = [(max(a, capture_start), min(b, capture_end), label, since)
             for a, b, label, since in intervals(messages)
             if max(a, capture_start) < min(b, capture_end)]
    starts = [s[0] for s in spans]
    exposure_ms = sum(b - a for a, b, _, _ in spans)
    counts = {"checkin": 0, "alert_on": 0, "object_on": 0}
    seen = set()
    for event in events:
        if event.get("type") != "event" or event.get("kind") not in counts:
            continue
        identity = event.get("id")
        if not identity:
            raise ValueError("event ids are required to deduplicate repeated captures")
        if identity in seen:
            continue
        seen.add(identity)
        t = event["recv_t"]
        i = bisect_right(starts, t) - 1
        if i < 0 or not (spans[i][0] <= t < spans[i][1]):
            continue
        _, _, actual, since = spans[i]
        if event["kind"] == "alert_on":
            limit_s = zones.get(actual.get("zone")) if actual.get("present") else None
            limit = limit_s * 1000 if limit_s is not None else None
            if limit is not None and t - since >= limit and event.get("info", {}).get("zone") == actual["zone"]:
                continue
        counts[event["kind"]] += 1
    minutes = exposure_ms / 60000
    return {"counts": counts, "observed_minutes": minutes,
            "per_minute": {kind: n / minutes if minutes else None for kind, n in counts.items()},
            "false_alarms_per_min": sum(counts.values()) / minutes if minutes else None}


def update_proof(proof, result, messages, events, commit):
    if any(m.get("src") != "live" for m in messages + events):
        raise ValueError("only live recordings can update measured proof")
    if "synthetic" in (proof.get("zone") or {}).get("method", "").lower():
        raise ValueError("synthetic proof cannot be promoted to measured evidence")
    if not result["observed_minutes"]:
        return dict(proof)
    out = prepare_update(proof, commit)
    out["false_alarms_per_min"] = result["false_alarms_per_min"]
    return out


def analyze_many(pairs):
    results = [analyze(messages, events) for messages, events in pairs]
    minutes = sum(r["observed_minutes"] for r in results)
    counts = {k: sum(r["counts"][k] for r in results) for k in ("checkin", "alert_on", "object_on")}
    return {"counts": counts, "observed_minutes": minutes,
            "per_minute": {k: n / minutes if minutes else None for k, n in counts.items()},
            "false_alarms_per_min": sum(counts.values()) / minutes if minutes else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("events", type=Path, help="captured events stamped with board recv_t")
    parser.add_argument("--more-pairs", nargs=2, action="append", default=[], type=Path, metavar=("SESSION", "EVENTS"))
    parser.add_argument("--proof", type=Path)
    args = parser.parse_args()
    messages, events = read_jsonl(args.session), read_jsonl(args.events)
    pairs = [(messages, events)] + [(read_jsonl(a), read_jsonl(b)) for a, b in args.more_pairs]
    result = analyze_many(pairs)
    messages = [m for a, _ in pairs for m in a]
    events = [e for _, b in pairs for e in b]
    if args.proof:
        require_board()
        proof = json.loads(args.proof.read_text())
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        args.proof.write_text(json.dumps(update_proof(proof, result, messages, events, commit), indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
