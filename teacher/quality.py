"""Numeric label-quality report; no camera or image input."""

import argparse
import json
import math
from pathlib import Path
from statistics import mean


def report(messages, min_hz=5, max_clipped=0.1, max_jitter_m=0.1):
    labels = sorted((m for m in messages if m.get("type") == "label"), key=lambda m: m["recv_t"])
    count = len(labels)
    span = (labels[-1]["recv_t"] - labels[0]["recv_t"]) / 1000 if count > 1 else 0
    hz = (count - 1) / span if span else None
    clipped = sum(bool(m.get("clipped")) for m in labels)
    empty = sum(not m.get("present") and not m.get("clipped") for m in labels)
    groups, current = [], []
    for m in labels:
        point = m.get("foot_m")
        valid = (m.get("present") and not m.get("clipped") and m.get("motion") == "still"
                 and isinstance(point, list) and len(point) == 2 and all(math.isfinite(x) for x in point))
        if current and (not valid or m.get("zone") != current[-1].get("zone") or m["recv_t"] - current[-1]["recv_t"] > 500):
            groups.append(current)
            current = []
        if valid:
            current.append(m)
    groups.append(current)
    squares = []
    for group in groups:
        if len(group) < 3:
            continue
        centre = [mean(m["foot_m"][i] for m in group) for i in (0, 1)]
        squares.extend(math.dist(m["foot_m"], centre) ** 2 for m in group)
    jitter = math.sqrt(mean(squares)) if squares else None
    gaps = sum(b["recv_t"] - a["recv_t"] > 1000 for a, b in zip(labels, labels[1:]))
    flags = []
    if hz is None or hz < min_hz:
        flags.append("insufficient processed-label rate")
    if count and clipped / count > max_clipped:
        flags.append("too many clipped labels")
    if gaps:
        flags.append("processed-label gaps exceed 1 s")
    if jitter is not None and jitter > max_jitter_m:
        flags.append("standing-still foot-point jitter exceeds threshold")
    return {"labels": count, "labels_per_second": hz, "clipped_share": clipped / count if count else None,
            "empty_frame_share": empty / count if count else None, "still_jitter_rms_m": jitter,
            "still_points": len(squares), "gaps_over_1s": gaps, "flags": flags,
            "thresholds": {"min_hz": min_hz, "max_clipped": max_clipped, "max_jitter_m": max_jitter_m}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--min-hz", type=float, default=5)
    parser.add_argument("--max-clipped", type=float, default=0.1)
    parser.add_argument("--max-jitter-m", type=float, default=0.1)
    args = parser.parse_args()
    messages = [json.loads(line) for line in args.session.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(report(messages, args.min_hz, args.max_clipped, args.max_jitter_m), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
