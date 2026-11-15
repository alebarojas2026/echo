"""Enter sourced power-meter readings and strict board egress-counter output."""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import subprocess

from proof.provenance import prepare_update, empty_proof


def egress_bytes(text):
    if not re.fullmatch(r"[0-9]+\s*", text):
        raise ValueError("egress output must be the integer stdout from board/egress.sh")
    return int(text)


def update(proof, commit, measured_at, mode=None, watts=None, source=None, egress=None, egress_source=None, duration_s=None, image_audit=None, egress_duration_s=None):
    datetime.fromisoformat(measured_at.replace("Z", "+00:00"))
    if watts is None and egress is None and image_audit is None:
        raise ValueError("supply measured watts, egress or an image audit")
    if watts is not None:
        if mode not in {"idle", "teaching", "radio_only"} or not source or not source.strip():
            raise ValueError("watts requires a mode and power-meter source/model")
        if isinstance(watts, bool) or not math.isfinite(watts) or watts <= 0:
            raise ValueError("watts must be a positive finite measurement")
        if duration_s is None or not math.isfinite(duration_s) or duration_s < 300:
            raise ValueError("power measurements require at least 300 s per mode")
        if re.search(r"datasheet|spec|rated|typical|[a-z][a-z0-9+.-]*://|www\.", source, re.I):
            raise ValueError("power source must be a meter measurement, not a specification or URL")
    if egress is not None and (not egress_source or not egress_source.strip()):
        raise ValueError("egress requires its capture source")
    out = prepare_update(proof, commit, measured_at)
    if watts is not None:
        values = dict(out.get("watts") or {"idle": None, "teaching": None, "radio_only": None, "source": None})
        if values.get("source") not in {None, source}:
            raise ValueError("existing watts use another meter source; keep measurements separate")
        values[mode], values["source"] = watts, source.strip()
        out["watts"] = values
    if egress is not None:
        out["bytes_out"] = egress_bytes(egress)
    if image_audit is not None:
        count = image_audit.get("count")
        if type(count) is not int or count<0 or not image_audit.get("folders") or not image_audit.get("containers"):
            raise ValueError("image count requires a complete measured folder/container audit")
        out["images_stored"] = count
    evidence = {"measured_at": measured_at, "commit": commit, "mode": mode, "watts": watts,
                "source": source, "bytes_out": out.get("bytes_out") if egress is not None else None,
                "egress_source": egress_source, "duration_s": duration_s,"egress_duration_s":egress_duration_s,
                "images_stored":out.get("images_stored") if image_audit is not None else None,"image_audit":image_audit}
    return out, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, default=Path(__file__).resolve().with_name("proof.json"))
    parser.add_argument("--mode", choices=["idle", "teaching", "radio_only"])
    parser.add_argument("--watts", type=float)
    parser.add_argument("--source", help="power meter model and measurement method")
    parser.add_argument("--egress", action="store_true", help="read the live board egress counter")
    parser.add_argument("--images",action="store_true",help="inspect required host paths and teacher container storage")
    parser.add_argument("--teacher-container",help="actual running App Lab teacher name/id from docker ps")
    parser.add_argument("--apps-dir",type=Path,help="App Lab apps folder, default: checkout owner's ArduinoApps")
    parser.add_argument("--check-meter",action="store_true",help="require agreement with the running /privacy meter")
    parser.add_argument("--duration-s", type=float, help="actual meter measurement duration; at least 300 s")
    parser.add_argument("--egress-source", help="counter capture method and interval")
    parser.add_argument("--egress-duration-s",type=float,help="actual full rehearsal counter interval")
    parser.add_argument("--measured-at", required=True, help="actual ISO measurement time, not entry time")
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text(encoding="utf-8")) if args.proof.exists() else empty_proof()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    try:
        if args.egress and (args.egress_duration_s is None or not math.isfinite(args.egress_duration_s) or args.egress_duration_s<=0):
            parser.error("--egress requires a positive --egress-duration-s")
        if args.egress: check_routes()
        egress = capture_egress() if args.egress else None
        if args.check_meter and not args.images: parser.error("--check-meter requires --images")
        audit = capture_images(args.teacher_container,args.apps_dir,args.check_meter) if args.images else None
        out, evidence = update(proof, commit, args.measured_at, args.mode, args.watts, args.source,
                               egress, args.egress_source, args.duration_s,audit,args.egress_duration_s)
        if args.egress: evidence["no_default_route"] = True
        schema = json.loads((Path(__file__).resolve().parents[1]/"contracts/schemas/proof.json").read_text())
        if audit is not None and "image_audit" in schema["properties"]:
            out["image_audit"] = {k:v for k,v in audit.items() if k!="count"} | {"measured_at":args.measured_at}
        from contracts.check import VALIDATORS
        VALIDATORS["proof"].evolve(schema=schema).validate(out)
    except ValueError as error:
        parser.error(str(error))
    # A separate local evidence log preserves the manual reading's own date/source.
    evidence_path = args.proof.with_suffix(".manual.jsonl")
    with evidence_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(evidence, allow_nan=False) + "\n")
    args.proof.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def capture_egress():
    from proof.provenance import require_board
    require_board()
    script = Path(__file__).resolve().parents[1] / "board/egress.sh"
    return subprocess.check_output(["bash", str(script), "count"], text=True)


def capture_images(container, apps=None, compare=False):
    from proof.provenance import require_board
    from proof.storage import audit, default_folders, check_meter
    require_board()
    result = audit(default_folders(Path(__file__).resolve().parents[1],apps),container)
    if compare: result["meter_images_agree"] = check_meter(result["count"])
    return result


def check_routes():
    for family in ("-4","-6"):
        if subprocess.check_output(["ip",family,"route","show","default"],text=True).strip():
            raise ValueError("privacy measurement requires no IPv4 or IPv6 default route")


if __name__ == "__main__":
    main()
