"""Publish numeric processed-frame liveness through a host-mounted directory."""

import json
from pathlib import Path


def write_heartbeat(path, label):
    target = Path(path)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"t": label["t"], "frame": label["frame"]}))
    temporary.replace(target)
