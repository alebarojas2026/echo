"""Where things are drawn, saved from the screen's align mode on the board (#510).

Two things, both for drawing only:
- the room alignment (how the hall scan sits on the layout): offset_m, yaw_deg, scale, cut_m, the
  same four numbers align mode saves as room.json;
- each hall beacon's xyz_m (nodes.json "hall" section), for the beacons nodes.json already has.

They live in one board-local file, data/layout.local.json (gitignored), never in radio/nodes.json:
the checkout stays clean for board/deploy.sh, and the brain and the radio side never see a change.
board/serve.py lays the beacon positions over its /nodes.json answer, and answers GET and POST
/layout with this module.
"""
import copy
import json
import math
import os
from pathlib import Path

ROOM_KEYS = ("offset_m", "yaw_deg", "scale", "cut_m")
XY_LIMIT_M = 100.0     # a hall beacon is 10-25 m from the layout; 100 m is a typo
Z_RANGE_M = (0.0, 10.0)
MAX_BODY = 8192


class Invalid(ValueError):
    """The body is not something align mode saves; the text says what was wrong."""


def _num(v, lo, hi) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def clean_room(room) -> dict:
    """The four alignment numbers, each in range, and nothing else."""
    if not isinstance(room, dict) or set(room) != set(ROOM_KEYS):
        raise Invalid(f"room must have exactly {', '.join(ROOM_KEYS)}")
    off = room["offset_m"]
    if not (isinstance(off, list) and len(off) == 2 and all(_num(v, -100, 100) for v in off)):
        raise Invalid("room.offset_m must be two numbers within 100 m")
    if not _num(room["yaw_deg"], -360, 360):
        raise Invalid("room.yaw_deg must be within -360..360")
    if not _num(room["scale"], 0.25, 4):
        raise Invalid("room.scale must be within 0.25..4")
    if not _num(room["cut_m"], 0, 20):
        raise Invalid("room.cut_m must be within 0..20 m")
    return {"offset_m": [float(v) for v in off], "yaw_deg": float(room["yaw_deg"]),
            "scale": float(room["scale"]), "cut_m": float(room["cut_m"])}


def hall_ids(nodes_doc) -> list:
    """The hall beacons nodes.json has, in its order."""
    hall = (nodes_doc or {}).get("hall") or {}
    return [b["node"] for b in hall.get("beacons", []) if isinstance(b, dict) and isinstance(b.get("node"), str)]


def clean_beacons(beacons, known) -> dict:
    """{node: [x, y, z] or None} for hall beacons nodes.json has; anything else is refused."""
    if not isinstance(beacons, list):
        raise Invalid("hall_beacons must be a list of {node, xyz_m}")
    out = {}
    for b in beacons:
        if not isinstance(b, dict) or set(b) != {"node", "xyz_m"}:
            raise Invalid("each hall beacon is exactly {node, xyz_m}")
        node, xyz = b["node"], b["xyz_m"]
        if node not in known:
            raise Invalid(f"{node!r} is not a hall beacon in radio/nodes.json ({', '.join(known) or 'none'})")
        if xyz is not None:
            ok = isinstance(xyz, list) and len(xyz) == 3 and all(_num(v, -XY_LIMIT_M, XY_LIMIT_M) for v in xyz[:2]) \
                and _num(xyz[2], *Z_RANGE_M)
            if not ok:
                raise Invalid(f"{node}: xyz_m must be [x, y, z] with x and y within {XY_LIMIT_M:g} m "
                              f"and z within {Z_RANGE_M[0]:g}..{Z_RANGE_M[1]:g} m, or null")
            xyz = [round(float(v), 3) for v in xyz]
        out[node] = xyz
    return out


def clean(body, nodes_doc) -> dict:
    """What a POST may change: {"room": {...}} and/or {"hall_beacons": [...]}, nothing else."""
    if not isinstance(body, dict) or not body or not set(body) <= {"room", "hall_beacons"}:
        raise Invalid("expected {\"room\": {...}} and/or {\"hall_beacons\": [...]}, nothing else")
    out = {}
    if "room" in body:
        out["room"] = clean_room(body["room"])
    if "hall_beacons" in body:
        out["hall"] = clean_beacons(body["hall_beacons"], hall_ids(nodes_doc))
    return out


class Store:
    """data/layout.local.json: {"room": {...} or null, "hall": {node: xyz or null}}."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            room = doc.get("room")
            hall = doc.get("hall") if isinstance(doc.get("hall"), dict) else {}
            return {"room": room if isinstance(room, dict) else None, "hall": hall}
        except (OSError, ValueError, AttributeError):
            return {"room": None, "hall": {}}

    def save(self, change: dict) -> dict:
        """Merge a cleaned change in and write the file atomically. Returns what is stored now."""
        doc = self.load()
        if "room" in change:
            doc["room"] = change["room"]
        doc["hall"].update(change.get("hall", {}))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        return doc

    def view(self, nodes_doc) -> dict:
        """The GET /layout answer: the room alignment, and every hall beacon with its position."""
        doc = self.load()
        overlaid = overlay(nodes_doc, doc)
        return {"room": doc["room"],
                "hall_beacons": [{"node": b["node"], "xyz_m": b.get("xyz_m")}
                                 for b in ((overlaid.get("hall") or {}).get("beacons") or [])
                                 if isinstance(b, dict) and "node" in b]}


def overlay(nodes_doc, stored) -> dict:
    """nodes.json with the saved hall positions put in. Only hall beacons' xyz_m ever change."""
    hall = stored.get("hall") or {}
    if not hall or not isinstance((nodes_doc or {}).get("hall"), dict):
        return nodes_doc
    doc = copy.deepcopy(nodes_doc)
    for b in doc["hall"].get("beacons", []):
        if isinstance(b, dict) and b.get("node") in hall:
            b["xyz_m"] = hall[b["node"]]
    return doc
