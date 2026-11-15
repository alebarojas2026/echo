"""The layout, read once from radio/nodes.json (CONTRACTS.md section 3).

Links (in file order), node positions, router and tray spots and zone ids all come from the
file. The modules below take these as their defaults; the brain itself passes the parsed
file down, so a test can run it on another layout.
"""
import json
from pathlib import Path

NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
DOC = json.loads(NODES_JSON.read_text(encoding="utf-8"))


def link_ids(doc=DOC):
    return tuple(link["id"] for link in doc["links"])


def positions(doc=DOC, key="nodes"):
    """{id: (x, y)} of the nodes, or of router_spots / tray_spots."""
    return {n["id"]: (float(n["xyz_m"][0]), float(n["xyz_m"][1])) for n in doc.get(key, [])}


def zone_ids(doc=DOC):
    return [int(z["id"]) for z in doc["zones"]]


LINKS = link_ids()
