"""Enter sourced power-meter readings and strict board egress-counter output."""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import subprocess

from proof.provenance import prepare_update


def egress_bytes(text):
    if not re.fullmatch(r"[0-9]+\s*", text):
        raise ValueError("egress output must be the integer stdout from board/egress.sh")
    return int(text)


def update(proof, commit, measured_at, mode=None, watts=None, source=None, egress=None, egress_source=None):
    datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    if watts is None and egress is None:
        raise ValueError("supply a measured watts reading or egress output")
    if watts is not None:
        if mode not in {"idle", "teaching", "radio_only"} or not source or not source.strip():
            raise ValueError("watts requires a mode and power-meter source/model")
        if isinstance(watts, bool) or not math.isfinite(watts) or watts < 0:
            raise ValueError("watts must be a nonnegative finite measurement")
    if egress is not None and (not egress_source or not egress_source.strip()):
        raise ValueError("egress requires its capture source")
    out = prepare_update(proof, commit)
    if watts is not None:
        values = dict(out.get("watts") or {"idle": None, "teaching": None, "radio_only": None, "source": None})
        if values.get("source") not in {None, source}:
            raise ValueError("existing watts use another meter source; keep measurements separate")
        values[mode], values["source"] = watts, source.strip()
        out["watts"] = values
    if egress is not None:
        out["bytes_out"] = egress_bytes(egress)
    evidence = {"measured_at": measured_at, "commit": commit, "mode": mode, "watts": watts,
                "source": source, "bytes_out": out.get("bytes_out") if egress is not None else None,
                "egress_source": egress_source}
    return out, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, default=Path(__file__).resolve().with_name("proof.json"))
    parser.add_argument("--mode", choices=["idle", "teaching", "radio_only"])
    parser.add_argument("--watts", type=float)
    parser.add_argument("--source", help="power meter model and measurement method")
    parser.add_argument("--egress-output", type=Path, help="saved stdout from board/egress.sh count")
    parser.add_argument("--egress-source", help="counter capture method and interval")
    parser.add_argument("--measured-at", required=True, help="actual ISO measurement time, not entry time")
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text(encoding="utf-8"))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        out, evidence = update(proof, commit, args.measured_at, args.mode, args.watts, args.source,
                               args.egress_output.read_text() if args.egress_output else None, args.egress_source)
    except ValueError as error:
        parser.error(str(error))
    # A separate local evidence log preserves the manual reading's own date/source.
    evidence_path = args.proof.with_suffix(".manual.jsonl")
    with evidence_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(evidence, allow_nan=False) + "\n")
    args.proof.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
