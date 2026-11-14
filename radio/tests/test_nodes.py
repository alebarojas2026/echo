"""Checks radio/nodes.json against CONTRACTS.md section 3.

The expected values below are copied by hand from section 3, so a typo in
either place shows up here.
"""
import json
import re
from pathlib import Path

import pytest

NODES_PATH = Path(__file__).resolve().parent.parent / "nodes.json"

# Section 3, written out by hand.
NODES = {
    "unoq": ("N", (1.0, 2.0, 1.0), {"receiver"}),
    "pi5": ("S", (1.0, 0.0, 1.0), {"router", "beacon", "receiver"}),
    "east": ("E", (2.0, 1.0, 1.0), {"beacon"}),
    "west": ("W", (0.0, 1.0, 1.0), {"beacon"}),
}
LINK_IDS = [
    "pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble",
    "west>unoq:ble", "east>pi5:ble", "west>pi5:ble",
]
ZONES = {1: ("NW", "Bed", 60), 2: ("NE", "Chair", None), 3: ("SW", "Hall", None), 4: ("SE", "Bathroom", 10)}
ROUTER_SPOTS = {"S-home": (1.0, 0.0, 1.0), "S-W30": (0.7, 0.0, 1.0), "S-E30": (1.3, 0.0, 1.0)}
TRAY_SPOTS = {"T1": (1.0, 0.2, 1.0)}
BEACON_IDS = {"pi5": "S", "east": "E", "west": "W"}


def zone_of(x, y):
    """The section 3 rule for a point inside the 2 x 2 m square."""
    return 1 + int(x >= 1) + 2 * int(y < 1)


@pytest.fixture(scope="module")
def doc():
    with open(NODES_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def nodes(doc):
    return {n["id"]: n for n in doc["nodes"]}


def test_version_and_frame(doc):
    assert doc["v"] == 2
    frame = doc["frame"]
    assert frame["units"] == "m"
    assert frame["origin"] == "south-west corner of the square"
    assert (frame["x"], frame["y"], frame["z"]) == ("east", "north", "up")
    assert frame["size_m"] == [2.0, 2.0]


def test_nodes_match_section_3(doc, nodes):
    assert len(doc["nodes"]) == len(nodes) == 4
    assert set(nodes) == set(NODES)
    for node_id, (side, xyz, roles) in NODES.items():
        node = nodes[node_id]
        assert node["side"] == side
        assert node["xyz_m"] == pytest.approx(xyz)
        assert set(node["roles"]) == roles
        assert len(node["roles"]) == len(roles)


def test_nodes_sit_on_their_side_midpoints_at_one_metre(doc, nodes):
    w, h = doc["frame"]["size_m"]
    midpoints = {"N": (w / 2, h), "S": (w / 2, 0.0), "E": (w, h / 2), "W": (0.0, h / 2)}
    for node in nodes.values():
        x, y, z = node["xyz_m"]
        assert (x, y) == pytest.approx(midpoints[node["side"]])
        assert z == pytest.approx(1.0)


def test_link_ids_and_endpoints(doc, nodes):
    links = doc["links"]
    assert [link["id"] for link in links] == LINK_IDS
    for link in links:
        assert link["id"] == f'{link["tx"]}>{link["rx"]}:{link["kind"]}'
        assert link["tx"] in nodes and link["rx"] in nodes
        assert link["tx"] != link["rx"]
        assert "receiver" in nodes[link["rx"]]["roles"]
        tx_role = "router" if link["kind"] == "wifi" else "beacon"
        assert link["kind"] in ("wifi", "ble")
        assert tx_role in nodes[link["tx"]]["roles"]


def test_expected_hz_is_null_or_measured(doc):
    # null until the baseline capture writes it, then a positive rate
    for link in doc["links"]:
        assert "expected_hz" in link
        hz = link["expected_hz"]
        assert hz is None or (isinstance(hz, (int, float)) and hz > 0)


def test_zones_match_section_3(doc):
    zones = {z["id"]: z for z in doc["zones"]}
    assert len(doc["zones"]) == 4
    assert set(zones) == set(ZONES)
    for zone_id, (corner, name, still) in ZONES.items():
        assert zones[zone_id]["corner"] == corner
        assert zones[zone_id]["name"] == name
        assert zones[zone_id]["still_alert_s"] == still
    assert doc["zone_rule"] == "zone = 1 + (x >= 1) + 2*(y < 1); 0 = empty"


@pytest.mark.parametrize("x, y, zone", [
    (0.5, 1.5, 1), (1.5, 1.5, 2), (0.5, 0.5, 3), (1.5, 0.5, 4),
    (0.0, 2.0, 1), (2.0, 2.0, 2), (0.0, 0.0, 3), (2.0, 0.0, 4),
    # the lines x = 1 and y = 1 belong to the east and north zones
    (1.0, 1.0, 2), (0.99, 1.0, 1), (1.0, 0.99, 4), (0.99, 0.99, 3),
])
def test_zone_formula_on_sample_points(x, y, zone):
    assert zone_of(x, y) == zone


def test_zone_corners_agree_with_formula(doc):
    w, h = doc["frame"]["size_m"]
    corner_points = {"NW": (0.25 * w, 0.75 * h), "NE": (0.75 * w, 0.75 * h),
                     "SW": (0.25 * w, 0.25 * h), "SE": (0.75 * w, 0.25 * h)}
    for zone in doc["zones"]:
        assert zone_of(*corner_points[zone["corner"]]) == zone["id"]


def test_router_spots(doc, nodes):
    spots = {s["id"]: s["xyz_m"] for s in doc["router_spots"]}
    assert len(doc["router_spots"]) == len(spots) == 3
    assert set(spots) == set(ROUTER_SPOTS)
    for spot_id, xyz in ROUTER_SPOTS.items():
        assert spots[spot_id] == pytest.approx(xyz)
    # S-home is where the router node sits
    assert spots["S-home"] == pytest.approx(nodes["pi5"]["xyz_m"])
    # the two other spots are the same distance west and east along the south wall
    home = spots["S-home"]
    assert spots["S-W30"][0] - home[0] == pytest.approx(-0.3)
    assert spots["S-E30"][0] - home[0] == pytest.approx(0.3)
    assert all(s[1] == pytest.approx(home[1]) and s[2] == pytest.approx(home[2]) for s in spots.values())


def test_tray_spots(doc, nodes):
    spots = {s["id"]: s["xyz_m"] for s in doc["tray_spots"]}
    assert set(spots) == set(TRAY_SPOTS)
    assert spots["T1"] == pytest.approx(TRAY_SPOTS["T1"])
    # T1 sits on the router-to-receiver line, inside the square, in the SE zone
    x, y, _ = spots["T1"]
    assert x == pytest.approx(nodes["pi5"]["xyz_m"][0]) == pytest.approx(nodes["unoq"]["xyz_m"][0])
    assert 0.0 < y < doc["frame"]["size_m"][1]
    assert zone_of(x, y) == 4


def test_beacon_payloads(doc, nodes):
    beacons = doc["beacons"]
    assert beacons["company_id"] == "FFFF"
    assert beacons["prefix_hex"] == "5253"
    payloads = {p["node"]: p for p in beacons["payloads"]}
    assert len(beacons["payloads"]) == len(payloads)
    assert {p["node"]: p["id"] for p in payloads.values()} == BEACON_IDS
    # every beacon node has a payload, and nothing else does
    assert set(payloads) == {n for n, node in nodes.items() if "beacon" in node["roles"]}
    for node_id, p in payloads.items():
        assert p["id"] == nodes[node_id]["side"]
        expected = beacons["company_id"] + beacons["prefix_hex"] + format(ord(p["id"]), "02X")
        assert p["data_hex"] == expected


def test_no_mac_or_device_addresses():
    text = NODES_PATH.read_text(encoding="utf-8")
    assert not re.search(r"\b[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}\b", text)
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text)
