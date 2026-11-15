"""The layout the fake feed and the fake brain use, from radio/nodes.json (CONTRACTS.md section 3).

Node positions, links, router spots, zones and their still limits all come from the file, so the
fake data follows a new layout the way the real code does. Only x and y are used: every antenna
is at the same height.
"""
import json
from pathlib import Path

NODES_JSON = Path(__file__).resolve().parent.parent / "radio" / "nodes.json"
MARGIN_M = 0.2   # section 6: the X-ray grid covers the layout plus 0.2 m on each side


class Layout:
    def __init__(self, nodes: dict):
        frame = nodes.get("frame") or {}
        self.size_m = tuple(frame.get("size_m") or (2.0, 2.0))
        self.strip_m = tuple(frame["strip_m"]) if frame.get("strip_m") else None
        self.split_x_m = frame.get("zone_split_x_m")
        self.nodes = {n["id"]: tuple(n["xyz_m"][:2]) for n in nodes["nodes"]}
        self.links = [(l["tx"], l["rx"], l["kind"]) for l in nodes["links"]]
        self.router_spots = {s["id"]: tuple(s["xyz_m"][:2]) for s in nodes.get("router_spots") or []}
        self.zones = {int(z["id"]): z.get("still_alert_s") for z in nodes["zones"]}
        # The square: 10 x 10 cells of 0.24 m. The desk layout: 16 x 12 cells of 0.125 m (section 6).
        cell = 0.125 if self.strip_m else 0.24
        self.grid = {"w": round((self.size_m[0] + 2 * MARGIN_M) / cell),
                     "h": round((self.size_m[1] + 2 * MARGIN_M) / cell),
                     "cell_m": cell, "origin_m": [-MARGIN_M, -MARGIN_M]}

    def zone_of(self, x: float, y: float) -> int:
        """Section 3. The square: 1 + (x >= half) + 2*(y < half). The strip: 1 + (x >= split), 0 off it."""
        if self.strip_m:
            w, h = self.strip_m
            return 1 + int(x >= self.split_x_m) if 0 <= x <= w and 0 <= y <= h else 0
        w, h = self.size_m
        return 1 + int(x >= w / 2) + 2 * int(y < h / 2)


def load(path=NODES_JSON) -> Layout:
    with open(path, encoding="utf-8") as f:
        return Layout(json.load(f))


LAYOUT = load()
