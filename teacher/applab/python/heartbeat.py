"""Publish numeric processed-frame liveness through a host-mounted directory."""

import json
from pathlib import Path


def write_heartbeat(path, label, box_w=None):
    """box_w: in the desk view, the one person's box width as a share of the frame width (a number,
    never a picture), so `python -m teacher.calibrate --near` can measure how near "in the strip" is."""
    target = Path(path)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({"t": label["t"], "frame": label["frame"], "box_w": box_w}))
    temporary.replace(target)
