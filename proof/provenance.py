"""Preserve the commit and date belonging to existing measured evidence."""

from datetime import datetime, timezone
from pathlib import Path
import platform


def measured(value):
    if isinstance(value, dict):
        return any(measured(v) for k, v in value.items() if k not in {"commit", "measured_at"})
    if isinstance(value, list):
        return any(measured(v) for v in value)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def prepare_update(proof, commit):
    if measured(proof) and proof.get("commit") not in {None, commit}:
        raise ValueError("proof has measurements from another commit; rerun proof.score at this commit")
    out = dict(proof)
    if not out.get("commit"):
        out["commit"] = commit
    if not out.get("measured_at"):
        out["measured_at"] = datetime.now(timezone.utc).isoformat()
    return out


def require_board():
    path = Path("/proc/device-tree/model")
    name = path.read_text().lower() if path.exists() else ""
    if platform.system() != "Linux" or not any(x in name for x in ("uno q", "qrb2210")):
        raise ValueError("measured timing updates require the UNO Q and its board clock")
