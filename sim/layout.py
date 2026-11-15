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
        self.names = {int(z["id"]): z.get("name", f"zone {z['id']}") for z in nodes["zones"]}
        self.centres = {int(z["id"]): tuple(z["centre_m"]) if z.get("centre_m") else self._square_centre(int(z["id"]))
                        for z in nodes["zones"]}
        self.tray = next((tuple(s["xyz_m"][:2]) for s in nodes.get("tray_spots") or [] if s["id"] == "T1"), None)
        # The square: 10 x 10 cells of 0.24 m. The desk layout: 16 x 12 cells of 0.125 m (section 6).
        cell = 0.125 if self.strip_m else 0.24
        self.grid = {"w": round((self.size_m[0] + 2 * MARGIN_M) / cell),
                     "h": round((self.size_m[1] + 2 * MARGIN_M) / cell),
                     "cell_m": cell, "origin_m": [-MARGIN_M, -MARGIN_M]}

    def _square_centre(self, zone: int) -> tuple:
        w, h = self.size_m
        return (w / 4 if zone in (1, 3) else 3 * w / 4, 3 * h / 4 if zone in (1, 2) else h / 4)

    def tour(self) -> list:
        """Every zone once, in a walkable order: rows from the south, alternating direction
        (the square: 3, 4, 2, 1; the strip: 1, 2)."""
        rows = sorted({round(c[1], 3) for c in self.centres.values()})
        out = []
        for i, y in enumerate(rows):
            row = sorted((z for z, c in self.centres.items() if round(c[1], 3) == y), key=lambda z: self.centres[z][0])
            out += row if i % 2 == 0 else row[::-1]
        return out

    def still_zone(self) -> int:
        """The zone with the shortest no-movement limit: where the alert is shown."""
        limited = [z for z, s in self.zones.items() if s]
        return min(limited, key=lambda z: self.zones[z]) if limited else max(self.zones)

    def calm_zone(self) -> int:
        """A zone that never alerts, next to the still zone if there is one."""
        calm = [z for z, s in self.zones.items() if not s] or [z for z in self.zones if z != self.still_zone()]
        still = self.centres[self.still_zone()]
        return min(calm, key=lambda z: (abs(self.centres[z][1] - still[1]), abs(self.centres[z][0] - still[0])))

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
