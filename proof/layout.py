"""The layout for proof/, read from radio/nodes.json (CONTRACTS.md section 3).

RADIO_SIGHT_NODES names another file, as it does for the brain, so the tests can run on
another layout without replacing the repo's copy.
"""
import json
import os
from pathlib import Path

# Historical square fixtures have no centre_m in their zones.
SQUARE_CENTRES = {1: (0.5, 1.5), 2: (1.5, 1.5), 3: (0.5, 0.5), 4: (1.5, 0.5)}


def nodes_path():
    return Path(os.environ.get("RADIO_SIGHT_NODES")
                or Path(__file__).resolve().parent.parent / "radio" / "nodes.json")


def load(path=None):
    return json.loads(Path(path or nodes_path()).read_text(encoding="utf-8"))


def is_strip(doc):
    """The desk layout: a strip in front of a desk, split into zones along x."""
    return "strip_m" in doc["frame"]


def is_spot(doc):
    """One zone, and a strip with no split: the strip is the one spot a person stands on."""
    return is_strip(doc) and len(doc["zones"]) == 1 and doc["frame"].get("zone_split_x_m") is None


def presence_line(doc):
    """The line that decides by itself on this layout (CONTRACTS.md section 6), or None. Where there is
    one, the brain decides with no model and no lesson, so proof asks for neither."""
    return (doc.get("presence") or {}).get("line") or None


def zones(doc):
    """{zone id: (x, y, name)}: each zone's centre and name."""
    out = {}
    for z in doc["zones"]:
        x, y = z.get("centre_m") or SQUARE_CENTRES[int(z["id"])]
        out[int(z["id"])] = (float(x), float(y), z.get("name") or f"zone {z['id']}")
    return out


def zone_at(doc, x, y):
    """The zone a floor point lies in, or 0 when it lies in none.

    A point on the strip's back edge (the desk edge) counts as outside: nobody stands on it.
    """
    if is_strip(doc):
        width, depth = doc["frame"]["strip_m"]
        if not (0 <= x <= width and 0 <= y < depth):
            return 0
        if is_spot(doc):
            return int(doc["zones"][0]["id"])
        split = float(doc["frame"]["zone_split_x_m"])
        return 1 + (x >= split)
    width, depth = doc["frame"]["size_m"]
    if not (0 <= x <= width and 0 <= y <= depth):
        return 0
    return 1 + (x >= width / 2) + 2 * (y < depth / 2)


def link_midpoints(doc):
    """{link id: (x, y)} of each link's midpoint."""
    at = {n["id"]: n["xyz_m"] for n in doc["nodes"]}
    out = {}
    for link in doc["links"]:
        a, b = at.get(link["tx"]), at.get(link["rx"])
        if a and b:
            out[link["id"]] = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return out


def link_zones(doc):
    """{link id: zone} for the links whose midpoint lies in a zone (the threshold baseline).

    On one spot, a file that marks its links with crosses_spot decides it instead: the marked links
    are the spot's, whatever their midpoints.
    """
    if is_spot(doc) and any("crosses_spot" in link for link in doc["links"]):
        return {link["id"]: int(doc["zones"][0]["id"]) for link in doc["links"] if link.get("crosses_spot")}
    out = {}
    enabled = {link["id"] for link in doc["links"] if link.get("classifier",True) is not False}
    for link, (x, y) in link_midpoints(doc).items():
        if link not in enabled: continue
        zone = zone_at(doc, x, y)
        if zone:
            out[link] = zone
    return out
