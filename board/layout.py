"""Where things are drawn, saved from the screen's align mode on the board (#510).

Three things, for drawing and the X-ray only:
- the room alignment (how the hall scan sits on the layout): offset_m, yaw_deg, scale, cut_m, the
  same four numbers align mode saves as room.json, and floor_m when the square stands on a tier;
- each hall beacon's xyz_m (nodes.json "hall" section), for the beacons nodes.json already has;
- each core device's xyz_m (nodes.json "nodes"), placed on site with align mode's guide (#721).
  When the router (the node with the "router" role) is placed, its router_spots move with it by
  the same amount, so a router_moved or router_home puts it where it really is.

They live in one board-local file, data/layout.local.json (gitignored), never in radio/nodes.json:
the checkout stays clean for board/deploy.sh. Nothing saved here can change which links exist,
the zones or the zone rule: only xyz_m values (and the router's spots) are ever replaced.

board/serve.py lays the saved positions over its /nodes.json answer and answers GET and POST
/layout with this module. The brain reads the same positions from data/nodes.local.json
(RADIO_SIGHT_NODES in its unit): radio/nodes.json with the saved positions applied, written on
every save and by the brain unit's ExecStartPre (`python -m board.layout write-nodes`), so the
brain takes a new placement when it next starts.
"""
import argparse
import copy
import json
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODES = REPO / "radio" / "nodes.json"
LAYOUT = REPO / "data" / "layout.local.json"
MERGED = REPO / "data" / "nodes.local.json"   # what the brain reads (RADIO_SIGHT_NODES)

ROOM_KEYS = ("offset_m", "yaw_deg", "scale", "cut_m")
# Optional: how far the hall model sits below our floor when the square stands on a tier (#547).
# The screen sends it only when it isn't 0, so a front-floor save is still the four keys.
FLOOR_KEY = "floor_m"
FLOOR_RANGE_M = (-2.0, 10.0)
XY_LIMIT_M = 100.0     # a hall beacon is 10-25 m from the layout; 100 m is a typo
Z_RANGE_M = (0.0, 10.0)
NODE_XY_M, NODE_Z_M = (-5.0, 5.0), (0.0, 3.0)   # a core device stands near the layout
MAX_NODES = 16
MAX_BODY = 8192


class Invalid(ValueError):
    """The body is not something align mode saves; the text says what was wrong."""


def _num(v, lo, hi) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi


def clean_room(room) -> dict:
    """The four alignment numbers and an optional floor_m, each in range, and nothing else."""
    if not isinstance(room, dict) or set(room) - {FLOOR_KEY} != set(ROOM_KEYS):
        raise Invalid(f"room must have exactly {', '.join(ROOM_KEYS)} (and optionally {FLOOR_KEY})")
    off = room["offset_m"]
    if not (isinstance(off, list) and len(off) == 2 and all(_num(v, -100, 100) for v in off)):
        raise Invalid("room.offset_m must be two numbers within 100 m")
    if not _num(room["yaw_deg"], -360, 360):
        raise Invalid("room.yaw_deg must be within -360..360")
    if not _num(room["scale"], 0.25, 4):
        raise Invalid("room.scale must be within 0.25..4")
    if not _num(room["cut_m"], 0, 20):
        raise Invalid("room.cut_m must be within 0..20 m")
    out = {"offset_m": [float(v) for v in off], "yaw_deg": float(room["yaw_deg"]),
           "scale": float(room["scale"]), "cut_m": float(room["cut_m"])}
    if FLOOR_KEY in room:
        if not _num(room[FLOOR_KEY], *FLOOR_RANGE_M):
            raise Invalid(f"room.floor_m must be within {FLOOR_RANGE_M[0]:g}..{FLOOR_RANGE_M[1]:g} m")
        out[FLOOR_KEY] = float(room[FLOOR_KEY])
    return out


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


def node_ids(nodes_doc) -> list:
    """The core devices nodes.json has, in its order."""
    return [n["id"] for n in (nodes_doc or {}).get("nodes", []) if isinstance(n, dict) and isinstance(n.get("id"), str)]


def clean_nodes(nodes, known) -> dict:
    """{id: [x, y, z]} for core devices nodes.json has; anything else is refused."""
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        raise Invalid(f"nodes must be a list of at most {MAX_NODES} {{id, xyz_m}}")
    out = {}
    for n in nodes:
        if not isinstance(n, dict) or set(n) != {"id", "xyz_m"}:
            raise Invalid("each node is exactly {id, xyz_m}")
        node, xyz = n["id"], n["xyz_m"]
        if node not in known:
            raise Invalid(f"{node!r} is not a node in radio/nodes.json ({', '.join(known) or 'none'})")
        if node in out:
            raise Invalid(f"{node} is listed twice")
        if not (isinstance(xyz, list) and len(xyz) == 3 and all(_num(v, *NODE_XY_M) for v in xyz[:2])
                and _num(xyz[2], *NODE_Z_M)):
            raise Invalid(f"{node}: xyz_m must be [x, y, z] with x and y within {NODE_XY_M[0]:g}..{NODE_XY_M[1]:g} m "
                          f"and z within {NODE_Z_M[0]:g}..{NODE_Z_M[1]:g} m")
        out[node] = [round(float(v), 3) for v in xyz]
    return out


def clean(body, nodes_doc) -> dict:
    """What a POST may change: "room", "hall_beacons" and "nodes", nothing else."""
    if not isinstance(body, dict) or not body or not set(body) <= {"room", "hall_beacons", "nodes"}:
        raise Invalid("expected {\"room\": {...}}, {\"hall_beacons\": [...]} and/or {\"nodes\": [...]}, "
                      "nothing else")
    out = {}
    if "room" in body:
        out["room"] = clean_room(body["room"])
    if "hall_beacons" in body:
        out["hall"] = clean_beacons(body["hall_beacons"], hall_ids(nodes_doc))
    if "nodes" in body:
        out["nodes"] = clean_nodes(body["nodes"], node_ids(nodes_doc))
    return out


class Store:
    """data/layout.local.json: {"room": {...} or null, "hall": {node: xyz or null}, "nodes": {id: xyz}}."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            room = doc.get("room")
            hall = doc.get("hall") if isinstance(doc.get("hall"), dict) else {}
            nodes = doc.get("nodes") if isinstance(doc.get("nodes"), dict) else {}
            return {"room": room if isinstance(room, dict) else None, "hall": hall, "nodes": nodes}
        except (OSError, ValueError, AttributeError):
            return {"room": None, "hall": {}, "nodes": {}}

    def save(self, change: dict) -> dict:
        """Merge a cleaned change in and write the file atomically. Returns what is stored now."""
        doc = self.load()
        if "room" in change:
            doc["room"] = change["room"]
        doc["hall"].update(change.get("hall", {}))
        if "nodes" in change:   # the whole placement: [] clears it
            doc["nodes"] = change["nodes"]
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
                                 if isinstance(b, dict) and "node" in b],
                "nodes": [{"id": i, "xyz_m": doc["nodes"][i]} for i in node_ids(nodes_doc) if i in doc["nodes"]]}


def overlay(nodes_doc, stored) -> dict:
    """nodes.json with the saved positions put in. Only xyz_m values change: hall beacons', core
    devices', and the router's spots (moved by as much as the router was)."""
    hall = stored.get("hall") or {}
    placed = stored.get("nodes") or {}
    has_hall = bool(hall) and isinstance((nodes_doc or {}).get("hall"), dict)
    if not has_hall and not placed:
        return nodes_doc
    doc = copy.deepcopy(nodes_doc)
    if has_hall:
        for b in doc["hall"].get("beacons", []):
            if isinstance(b, dict) and b.get("node") in hall:
                b["xyz_m"] = hall[b["node"]]
    for n in doc.get("nodes", []):
        xyz = placed.get(n.get("id")) if isinstance(n, dict) else None
        if not xyz:
            continue
        if "router" in (n.get("roles") or []) and isinstance(n.get("xyz_m"), list) and len(n["xyz_m"]) == 3:
            delta = [new - old for new, old in zip(xyz, n["xyz_m"])]
            for spot in doc.get("router_spots", []):
                if isinstance(spot, dict) and isinstance(spot.get("xyz_m"), list) and len(spot["xyz_m"]) == 3:
                    spot["xyz_m"] = [round(v + d, 3) for v, d in zip(spot["xyz_m"], delta)]
        n["xyz_m"] = list(xyz)
    return doc


def write_nodes(nodes=NODES, layout_path=LAYOUT, out=MERGED) -> bool:
    """Write radio/nodes.json with the saved positions applied to out, atomically. With a saved file
    that can't be used, out is radio/nodes.json as it is. True if saved positions were applied."""
    if Path(out).resolve() == Path(nodes).resolve():
        raise ValueError(f"won't write over {nodes}: the merged copy goes to its own file")
    doc = json.loads(Path(nodes).read_text(encoding="utf-8"))
    try:
        merged = overlay(doc, Store(layout_path).load())
    except (TypeError, ValueError, AttributeError) as e:
        print(f"layout: saved positions can't be applied ({e}); writing radio/nodes.json as it is", file=sys.stderr)
        merged = doc
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return merged is not doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Saved positions: write the merged nodes file the brain reads")
    ap.add_argument("what", choices=("write-nodes",))
    ap.add_argument("--nodes", default=str(NODES))
    ap.add_argument("--layout", default=str(LAYOUT))
    ap.add_argument("--out", default=os.environ.get("RADIO_SIGHT_NODES") or str(MERGED))
    args = ap.parse_args(argv)
    applied = write_nodes(args.nodes, args.layout, args.out)
    print(f"layout: wrote {args.out} ({'with the saved positions' if applied else 'as radio/nodes.json'})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
