"""Render PROOF.md tables from measured proof.json; unknown values stay __."""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re


START, END = "<!-- proof-json:start -->", "<!-- proof-json:end -->"


def numeric(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("measurements must be nonnegative finite numbers or null")
    return value


def display(value, suffix=""):
    value = numeric(value)
    return "__" if value is None else f"{value:.4g}{suffix}"


def cell(value):
    return re.sub(r"(?<!\\)\|", r"\\|", str(value)).replace("\n", " ").replace("\r", " ")


def agreement(section):
    correct, total = numeric(section.get("correct")), numeric(section.get("total"))
    if correct is None or total is None or total == 0:
        return "__", "__"
    if int(correct) != correct or int(total) != total or correct > total:
        raise ValueError("agreement counts must be integers with correct <= total")
    return f"{int(correct)}/{int(total)} ({100 * correct / total:.1f}%)", f"{int(total)} decisions"


def measurements(proof):
    zone = proof.get("zone") or {}
    if "synthetic" in zone.get("method", "").lower():
        raise ValueError("synthetic self-tests cannot populate the measured proof table")
    zone_value, zone_n = agreement(zone)
    ci = zone.get("ci95")
    if ci is not None:
        if len(ci) != 2 or any(numeric(v) is None or v > 1 for v in ci) or ci[0] > ci[1]:
            raise ValueError("invalid 95% interval")
    if zone_value != "__":
        zone_value += f"; 95% CI {100*ci[0]:.1f}–{100*ci[1]:.1f}%" if ci else "; 95% CI __"
        sessions = zone.get("sessions") or []
        zone_n += f"; {len(sessions)} sessions; {display(zone.get('walkers'))} walkers"
    po_value, po_n = agreement(proof.get("person_vs_object") or {})
    threshold_value, threshold_n = agreement(proof.get("threshold_zone") or {})
    timing = proof.get("ms_per_decision") or {}
    timing_value = "__"
    if timing.get("p50") is not None or timing.get("p95") is not None:
        timing_value = f"p50 {display(timing.get('p50'), ' ms')}; p95 {display(timing.get('p95'), ' ms')}"
    watts = proof.get("watts") or {}
    watt_value = "__"
    if any(watts.get(k) is not None for k in ("idle", "teaching", "radio_only")):
        watt_value = "; ".join(f"{k.replace('_', ' ')} {display(watts.get(k), ' W')}" for k in ("idle", "teaching", "radio_only"))
    primary = {
        "Zone accuracy": (zone_value, zone_n),
        "Radio vs camera zone agreement": (zone_value, zone_n),
        "Person vs object accuracy": (po_value, po_n),
        "Time to train on the board": (display(proof.get("train_s"), " s"), "__"),
        "Time per decision": (timing_value, "__"),
        "Board power draw": (watt_value, "__"),
    }
    extras = [
        ("Threshold zone baseline", threshold_value, "Fixed 3 dB strongest-link baseline", threshold_n),
        ("False presence episodes per minute", display(proof.get("false_alarms_per_min")),
         "Episodes / labeled-empty minutes; see proof/README.md", "__"),
        ("Bytes sent out", display(proof.get("bytes_out")), "Measured network egress", "__"),
        ("Images stored", display(proof.get("images_stored")), "Measured storage audit", "__"),
        ("Models on board", display(proof.get("models_on_board")), "Installed model inventory", "__"),
    ]
    return primary, extras


def render(document, proof):
    primary, extras = measurements(proof)
    date, commit = proof.get("measured_at"), proof.get("commit")
    measured = any(v != "__" for v, _ in primary.values()) or any(v != "__" for _, v, _, _ in extras)
    if measured:
        if not isinstance(date, str) or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
            raise ValueError("measured rows require an ISO date and commit id")
        datetime.fromisoformat(date.replace("Z", "+00:00"))
    else:
        date = commit = "__"
    if START in document or END in document:
        if document.count(START) != 1 or document.count(END) != 1 or document.index(START) > document.index(END):
            raise ValueError("malformed generated proof block")
        before, rest = document.split(START)
        _, after = rest.split(END)
        document = before.rstrip() + "\n" + after
    lines = []
    for line in document.splitlines():
        if line.startswith("|"):
            columns = [part.strip() for part in re.split(r"(?<!\\)\|", line)[1:-1]]
            key = next((k for k in primary if columns and columns[0].startswith(k)), None)
            if key is not None and len(columns) == 6:
                value, n = primary[key]
                row_date, row_commit = (date, commit) if value != "__" else ("__", "__")
                columns = [columns[0], value, columns[2], n, row_date, row_commit]
                line = "| " + " | ".join(cell(c) for c in columns) + " |"
        lines.append(line)
    block = [START, "", "## Additional proof.json measurements", "",
             "| Number | Value | Method | N | Date | Commit |", "|---|---|---|---|---|---|"]
    for label, value, method, n in extras:
        row_date, row_commit = (date, commit) if value != "__" else ("__", "__")
        block.append("| " + " | ".join(cell(c) for c in (label, value, method, n, row_date, row_commit)) + " |")
    block.extend(["", END])
    return "\n".join(lines).rstrip() + "\n\n" + "\n".join(block) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--proof", type=Path, default=root / "proof" / "proof.json")
    parser.add_argument("--document", type=Path, default=root / "PROOF.md")
    parser.add_argument("--output", type=Path, help="explicit output path; omit to preview on stdout")
    args = parser.parse_args()
    output = render(args.document.read_text(encoding="utf-8"), json.loads(args.proof.read_text(encoding="utf-8")))
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
