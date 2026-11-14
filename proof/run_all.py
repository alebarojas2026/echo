"""Run proof stages from recorded sessions and list missing evidence."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from proof.score import load_session


def plan(folder, output, baseline, document, on_board=False):
    folder, output = Path(folder), Path(output)
    groups = {"train": [], "heldout": [], "object": []}
    sessions = []
    missing = []
    for path in sorted(folder.glob("*.jsonl")):
        if path.name.endswith((".states.jsonl", ".events.jsonl")):
            continue
        session = load_session(path)
        purpose = session["meta"].get("purpose")
        if purpose in groups:
            groups[purpose].append(str(path))
            sessions.append((path, session))
    if not groups["train"]:
        missing.append("training session: meta.purpose=train")
    if not groups["heldout"]:
        missing.append("held-out session: meta.purpose=heldout")
    if not groups["object"]:
        missing.append("object training session: meta.purpose=object")
    if not Path(baseline).is_file():
        missing.append(f"20 s empty-room baseline artifact: {baseline}")
    commands = []
    if groups["train"] and groups["heldout"] and Path(baseline).is_file():
        commands.append([sys.executable, "-m", "proof.score", "--train", *groups["train"], *groups["object"],
                         "--heldout", *groups["heldout"], "--baseline", str(baseline), "--output", str(output)]
                        + (["--on-board"] if on_board else []))
    timing_pairs = []
    for path, session in sessions:
        if session["meta"].get("purpose") != "heldout":
            continue
        states = path.with_suffix(".states.jsonl")
        if states.is_file() and commands:
            timing_pairs.append((str(path), str(states)))
        else:
            missing.append(f"attributed state timing capture: {states}")
    if timing_pairs:
        command = [sys.executable, "-m", "proof.latency", *timing_pairs[0], "--proof", str(output)]
        for pair in timing_pairs[1:]:
            command.extend(["--more-pairs", *pair])
        commands.append(command)
    # Negative recordings are declared explicitly; waves/objects are not negative tests.
    manifest = folder / "proof-plan.json"
    negative = json.loads(manifest.read_text()).get("negative_sessions", []) if manifest.exists() else []
    known = {s["meta"]["session"]: (path, s["meta"].get("purpose")) for path, s in sessions}
    if not negative:
        missing.append(f"empty/still negative-session ids in {manifest}")
    # Combine negative sessions so each exposure contributes to the final rate.
    negative_pairs = []
    for identity in negative:
        entry = known.get(identity)
        if entry is None:
            missing.append(f"declared negative session: {identity}")
            continue
        path, purpose = entry
        if purpose != "heldout":
            missing.append(f"negative session {identity}: needs purpose=heldout, got {purpose}")
            continue
        events = path.with_suffix(".events.jsonl")
        if not events.exists() or not events.read_text(encoding="utf-8").strip():
            missing.append(f"captured negative events: {events}")
            continue
        negative_pairs.append((str(path), str(events)))
    if commands:
        if negative_pairs:
            path, events = negative_pairs[0]
            command = [sys.executable, "-m", "proof.false_alarms", path, events, "--proof", str(output)]
            for pair in negative_pairs[1:]:
                command.extend(["--more-pairs", *pair])
            commands.append(command)
        commands.append([sys.executable, "-m", "proof.render_table", "--proof", str(output),
                         "--document", str(document), "--output", str(document)])
    return commands, missing


def missing_metrics(proof):
    fields = [("zone agreement", (proof.get("zone") or {}).get("total")),
              ("person/object agreement", (proof.get("person_vs_object") or {}).get("total")),
              ("training time on board", proof.get("train_s")),
              ("decision p95 on board", (proof.get("ms_per_decision") or {}).get("p95")),
              ("false-event rate", proof.get("false_alarms_per_min")),
              ("radio-only power measurement", (proof.get("watts") or {}).get("radio_only")),
              ("idle power measurement", (proof.get("watts") or {}).get("idle")),
              ("teaching power measurement", (proof.get("watts") or {}).get("teaching")),
              ("measured images stored", proof.get("images_stored")),
              ("installed model inventory", proof.get("models_on_board")),
              ("measured egress bytes", proof.get("bytes_out"))]
    return [label for label, value in fields if value is None]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("sessions", type=Path)
    parser.add_argument("--baseline", type=Path, default=root / "data/sessions/baseline.json")
    parser.add_argument("--output", type=Path, default=root / "proof/proof.json")
    parser.add_argument("--document", type=Path, default=root / "PROOF.md")
    parser.add_argument("--on-board", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    commands, missing = plan(args.sessions, args.output, args.baseline, args.document, args.on_board)
    for command in commands:
        if args.dry_run:
            print(json.dumps(command))
        else:
            subprocess.run(command, check=True)
    if not args.dry_run and args.output.exists():
        missing += missing_metrics(json.loads(args.output.read_text()))
    for item in missing:
        print("missing: " + item)
    if missing:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
