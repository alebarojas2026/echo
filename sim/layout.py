"""The layout the fake feed and the fake brain use, from radio/nodes.json (CONTRACTS.md section 3).

Node positions, links, router spots, zones and their still limits all come from the file, so the
fake data follows a new layout the way the real code does. Only x and y are used: every antenna
is at the same height.
"""
import json
import math
import os
from pathlib import Path

# RADIO_SIGHT_NODES names another layout file, as it does for the brain. Unset, it is radio/nodes.json.
NODES_JSON = Path(os.environ.get("RADIO_SIGHT_NODES")
                  or Path(__file__).resolve().parent.parent / "radio" / "nodes.json")
MARGIN_M = 0.2   # section 6: the X-ray grid covers the layout plus 0.2 m on each side


class Layout:
    def __init__(self, nodes: dict):
        frame = nodes.get("frame") or {}
        self.size_m = tuple(frame.get("size_m") or (2.0, 2.0))
        self.strip_m = tuple(frame["strip_m"]) if frame.get("strip_m") else None
        self.split_x_m = frame.get("zone_split_x_m")
        # section 6, Armed: how long an appearance must last to be an intrusion (3 s when the file has none)
        self.hold_s = float((nodes.get("armed") or {}).get("hold_s", 3.0))
        # "presence" in the file: the one line that decides whether somebody is there (the gate: the Wi-Fi line
        # from Pi A to Pi B, which fell 15 to 21 dB with a person on the kit). The fake feed drops it that far.
        self.presence_line = (nodes.get("presence") or {}).get("line")
        self.nodes = {n["id"]: tuple(n["xyz_m"][:2]) for n in nodes["nodes"]}
        self.node_names = {n["id"]: n.get("name") or n["id"] for n in nodes["nodes"]}
        self.links = [(l["tx"], l["rx"], l["kind"]) for l in nodes["links"]]
        self.router_spots = {s["id"]: tuple(s["xyz_m"][:2]) for s in nodes.get("router_spots") or []}
        self.zones = {int(z["id"]): z.get("still_alert_s") for z in nodes["zones"]}
        self.names = {int(z["id"]): z.get("name", f"zone {z['id']}") for z in nodes["zones"]}
        self.centres = {int(z["id"]): tuple(z["centre_m"]) if z.get("centre_m") else self._square_centre(int(z["id"]))
                        for z in nodes["zones"]}
        self.spots = {s["id"]: tuple(s["xyz_m"][:2]) for s in nodes.get("tray_spots") or []}
        self.tray = self.spots.get("T1")
        # The square: 10 x 10 cells of 0.24 m. The desk layout: 16 x 12 cells of 0.125 m (section 6).
        cell = 0.125 if self.strip_m else 0.24
        self.grid = {"w": round((self.size_m[0] + 2 * MARGIN_M) / cell),
                     "h": round((self.size_m[1] + 2 * MARGIN_M) / cell),
                     "cell_m": cell, "origin_m": [-MARGIN_M, -MARGIN_M]}
        # How a person blocks a link in the fake feed: the full drop within body_m of the line, then
        # fading with width_m. The square's 2 m links were fine with a thin line. The strip's links are 0.6-1.2 m and
        # some pass 0.2 m from a zone centre, so there the body's own width counts: a person at a zone
        # centre drops both links that cross their side by 4 dB or more, and the links over the desk
        # (0.3 m away) by under 1 dB. The x-ray bump shrinks with the cells (0.24 m -> 0.125 m).
        self.body_m, self.width_m, self.bump_m = (0.1, 0.13, 0.15) if self.strip_m else (0.0, 0.2, 0.3)

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
        if not calm:
            return self.still_zone()   # one zone: there is nowhere else to stand
        still = self.centres[self.still_zone()]
        return min(calm, key=lambda z: (abs(self.centres[z][1] - still[1]), abs(self.centres[z][0] - still[0])))

    def zone_of(self, x: float, y: float) -> int:
        """Section 3. The square: 1 + (x >= half) + 2*(y < half). The strip: 1 + (x >= split), 0 off it.
        A strip with no split is one spot: its one zone anywhere on it."""
        if self.strip_m:
            w, h = self.strip_m
            if not (0 <= x <= w and 0 <= y <= h):
                return 0
            return min(self.zones) if self.split_x_m is None else 1 + int(x >= self.split_x_m)
        w, h = self.size_m
        if not (0 <= x <= w and 0 <= y <= h):
            return 0
        return 1 + int(x >= w / 2) + 2 * int(y < h / 2)

    def prop_node(self) -> str:
        """The device that gets unplugged in a path ({"node": "prop"}): the east beacon where the layout
        has one, else the first node that only sends, else the device farthest from the board that
        isn't the router (the gate: Pi B)."""
        if "east" in self.nodes:
            return "east"
        heard = {rx for _, rx, _ in self.links}
        only_sends = [tx for tx, _, _ in self.links if tx not in heard]
        if only_sends:
            return only_sends[0]
        routers = {tx for tx, _, kind in self.links if kind == "wifi"}
        board = self.nodes.get("unoq") or next(iter(self.nodes.values()))
        others = [n for n in self.nodes if n not in routers and n != "unoq"] or list(self.nodes)
        return max(others, key=lambda n: math.dist(self.nodes[n], board))

    def presence_ends(self):
        """(tx, rx) of the presence line, or None on a layout without one."""
        if not self.presence_line:
            return None
        tx, _, rest = self.presence_line.partition(">")
        return tx, rest.partition(":")[0]

    def in_the_line(self) -> tuple:
        """Where a thing left "in the line" stands ({"on": "line"} in a path): the middle of the presence
        line, or on a layout without one the tray spot, on the router's link."""
        ends = self.presence_ends()
        if not ends and self.tray:
            return self.tray
        ends = ends or self.links[0][:2]   # no tray spot either: the middle of the layout's first link
        (ax, ay), (bx, by) = self.nodes[ends[0]], self.nodes[ends[1]]
        return (round((ax + bx) / 2, 3), round((ay + by) / 2, 3))

    def area_width(self) -> float:
        return (self.strip_m or self.size_m)[0]

    def zone(self, name) -> int:
        """A zone by number, or by its part in a path, so one path plays on every layout:
        "tour1", "tour2", ... the stops of tour() in turn (wrapping round when there are fewer
        zones), "still" the zone with the shortest no-movement limit, "calm" the zone next to it."""
        if isinstance(name, int):
            return name
        if name == "still":
            return self.still_zone()
        if name == "calm":
            return self.calm_zone()
        if name.startswith("tour"):
            tour = self.tour()
            return tour[(int(name[4:]) - 1) % len(tour)]
        raise ValueError(f"unknown zone {name!r}")

    def end_near(self, zone: int) -> str:
        """The end of the area nearer the zone's centre ("west" on a tie)."""
        return "east" if self.centres[zone][0] > self.area_width() / 2 else "west"

    def resolve(self, path: dict) -> dict:
        """A path written against the layout instead of in metres, turned into metres:
        a waypoint {"t", "zone": z, "dx", "dy"} stands at zone z's centre (plus an offset), where z
        is a number or a part (see zone(): "tour1", "still", "calm");
        {"t", "zone": z, "edge": "west" | "east" | "near"} is at that end of the area, level with zone z;
        {"t", "zone": z, "outside": "west" | "east" | "near"} is 0.4 m past that end (not in the area);
        an object {"spot": "T1"} sits on that tray spot, {"near": node, "inset_m": d} next to the
        node, d metres in from it along x. Points and objects already in metres are kept.
        An outage {"node": "prop"}, or an object {"near": "prop"}, is at the device this layout
        unplugs (prop_node). An object {"on": "line"} stands in the line the dead-zone advice is about
        (in_the_line)."""
        out = dict(path)
        if path.get("person"):
            out["person"] = [self._waypoint(p) for p in path["person"]]
        if path.get("objects"):
            out["objects"] = [self._object(o) for o in path["objects"]]
        if path.get("outages"):
            out["outages"] = [dict(o, node=self.prop_node()) if o.get("node") == "prop" else o for o in path["outages"]]
        if path.get("router") and out.get("objects"):
            first = out["objects"][0]
            out["router"] = [dict(r, spot=self.clear_spot((first["x"], first["y"]))) if r["spot"] == "clear" else r
                             for r in path["router"]]
        return out

    def clear_spot(self, xy) -> str:
        """A router step {"spot": "clear"}: the spot other than S-home whose link to the board passes
        farthest from the path's first object (the first in the file on a tie), as the advice picks it."""
        def away(spot):
            (ax, ay), (bx, by) = self.router_spots[spot], self.nodes["unoq"]
            f = max(0.0, min(1.0, ((xy[0] - ax) * (bx - ax) + (xy[1] - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
            return round(math.dist(xy, (ax + f * (bx - ax), ay + f * (by - ay))), 3)
        spots = [s for s in self.router_spots if s != "S-home"]
        return max(spots, key=lambda s: (away(s), -spots.index(s)))

    def _waypoint(self, p: dict) -> dict:
        if "zone" not in p or "x" in p:
            return p
        p = dict(p)
        zone = self.zone(p.pop("zone"))
        x, y = self.centres[zone]
        end = p.pop("edge", None) or p.get("outside")
        if end == "near":
            end = self.end_near(zone)
        if end:
            past = 0.4 if p.pop("outside", None) else 0.0
            x = -past if end == "west" else self.area_width() + past
        p["x"], p["y"] = round(x + p.pop("dx", 0.0), 3), round(y + p.pop("dy", 0.0), 3)
        return p

    def _object(self, o: dict) -> dict:
        o = dict(o)
        if "spot" in o:
            o["x"], o["y"] = self.spots[o.pop("spot")]
        elif o.get("on") == "line":
            del o["on"]
            o["x"], o["y"] = self.in_the_line()
        elif "near" in o:
            near = o.pop("near")
            x, y = self.nodes[self.prop_node() if near == "prop" else near]
            inset = o.pop("inset_m", 0.15)
            o["x"], o["y"] = round(x - inset if x >= self.area_width() / 2 else x + inset, 3), y
        return o


def load(path=NODES_JSON) -> Layout:
    with open(path, encoding="utf-8") as f:
        return Layout(json.load(f))


LAYOUT = load()
