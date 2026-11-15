"""The layout is written in three places: radio/nodes.json, CONTRACTS.md section 3 and contracts/schemas.

nodes.json is the one code reads, and it is a copy of one of radio/layouts/ (python -m radio.use_layout).
The desk layout's numbers are written out by hand below and checked against radio/layouts/desk.json, so
these tests pass whichever layout is in use; the schemas are checked against every layout file. They fail
when one of the three is changed without the others, so the next layout change shows up here and not on
the demo desk.
"""
import json
import math
import re
from pathlib import Path

import pytest

from contracts import check

REPO = Path(__file__).resolve().parents[2]
ACTIVE = json.loads((REPO / "radio" / "nodes.json").read_text(encoding="utf-8"))   # the layout in use
LAYOUTS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((REPO / "radio" / "layouts").glob("*.json"))}
DOC = LAYOUTS["desk"]   # the desk layout: the one whose numbers are written out below
SCHEMAS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (REPO / "contracts" / "schemas").glob("*.json")}
DEFS = SCHEMAS["common"]["$defs"]
SECTION_3 = (REPO / "CONTRACTS.md").read_text(encoding="utf-8").split("## 3. ")[1].split("## 4. ")[0]

# Section 3, written out by hand.
NODES = {"unoq": (1.1, 0.6, 1.0), "pi5": (0.8, 1.1, 1.0), "pi5b": (0.5, 0.6, 1.0),
         "east": (1.6, 0.25, 1.0), "west": (0.0, 0.25, 1.0)}
LINKS = ["pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble",
         "pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "east>pi5b:ble", "west>pi5b:ble", "pi5b>pi5:ble"]
ZONES = {1: ("W", "Left", (0.4, 0.3), 10), 2: ("E", "Right", (1.2, 0.3), 10)}
ROUTER_SPOTS = {"S-home": (0.8, 1.1, 1.0), "S-W30": (0.5, 1.1, 1.0), "S-E30": (1.1, 1.1, 1.0)}
BEACONS = {"FFFF525353": "pi5", "FFFF525342": "pi5b", "FFFF525345": "east", "FFFF525357": "west"}
HALL_BEACONS = {"FFFF525348": "h", "FFFF52534A": "j"}
RECEIVERS = ["unoq", "pi5", "pi5b"]
HALL_LINKS = ["h>unoq:ble", "j>unoq:ble", "h>pi5:ble", "j>pi5:ble", "h>pi5b:ble", "j>pi5b:ble"]


def zone_of(x, y):
    """The section 3 rule."""
    return 1 + int(x >= 0.8) if 0 <= x <= 1.6 and 0 <= y <= 0.6 else 0


def test_nodes_json_is_a_copy_of_one_of_the_layout_files():
    assert ACTIVE in LAYOUTS.values()
    assert LAYOUTS[ACTIVE["layout"]] == ACTIVE


def test_the_desk_layout_file_is_the_desk_layout():
    assert DOC["v"] == 2 and DOC["layout"] == "desk"
    frame = DOC["frame"]
    assert (frame["size_m"], frame["strip_m"], frame["zone_split_x_m"]) == ([1.6, 1.1], [1.6, 0.6], 0.8)
    assert {n["id"]: tuple(n["xyz_m"]) for n in DOC["nodes"]} == NODES
    assert [link["id"] for link in DOC["links"]] == LINKS
    assert {z["id"]: (z["side"], z["name"], tuple(z["centre_m"]), z["still_alert_s"]) for z in DOC["zones"]} == ZONES
    assert {s["id"]: tuple(s["xyz_m"]) for s in DOC["router_spots"]} == ROUTER_SPOTS
    assert {s["id"]: tuple(s["xyz_m"]) for s in DOC["tray_spots"]} == {"T1": (0.86, 1.0, 1.0)}
    assert {p["data_hex"]: p["node"] for p in DOC["beacons"]["payloads"]} == BEACONS


def test_every_link_is_its_id_and_ends_at_a_receiver():
    roles = {n["id"]: n["roles"] for n in DOC["nodes"]}
    for link in DOC["links"]:
        assert link["id"] == f"{link['tx']}>{link['rx']}:{link['kind']}"
        assert "receiver" in roles[link["rx"]]
        assert ("router" if link["kind"] == "wifi" else "beacon") in roles[link["tx"]]
    assert [link["kind"] for link in DOC["links"]].count("wifi") == 2


def test_the_router_and_every_spot_sit_on_the_desk_and_home_is_pi5():
    assert ROUTER_SPOTS["S-home"] == NODES["pi5"]
    for xyz in list(ROUTER_SPOTS.values()) + [tuple(s["xyz_m"]) for s in DOC["tray_spots"]]:
        assert zone_of(xyz[0], xyz[1]) == 0   # on the desk top, never in a zone


def test_zones_follow_the_rule():
    assert "zone = 1 + (x >= 0.8) when 0 <= x <= 1.6 and 0 <= y <= 0.6" in DOC["zone_rule"]
    for zone in DOC["zones"]:
        assert zone_of(*zone["centre_m"]) == zone["id"]
    assert [zone_of(x, y) for x, y in [(0.0, 0.0), (0.79, 0.6), (0.8, 0.3), (1.6, 0.6)]] == [1, 1, 2, 2]
    assert [zone_of(x, y) for x, y in [(-0.01, 0.3), (1.61, 0.3), (0.4, -0.01), (0.4, 0.61), (0.86, 1.0)]] == [0] * 5


def test_the_schemas_name_the_same_nodes_links_spots_and_zones():
    assert DEFS["node"]["enum"] == [n["id"] for n in DOC["nodes"]]
    assert DEFS["near"]["enum"] == DEFS["node"]["enum"] + [None]
    assert DEFS["link"]["enum"] == LINKS
    assert DEFS["router_spot"]["enum"] == list(ROUTER_SPOTS)
    assert DEFS["zone"]["maximum"] == len(DOC["zones"])
    assert SCHEMAS["label"]["properties"]["zone"]["maximum"] == len(DOC["zones"])
    state = SCHEMAS["state"]["properties"]
    assert state["alert"]["properties"]["zone"]["maximum"] == len(DOC["zones"])
    # a spot to move the router to, or null where the router stays put (a layout with a presence line)
    assert state["advice"]["properties"]["to_spot"]["enum"] == [s for s in ROUTER_SPOTS if s != "S-home"] + [None]


@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_the_schemas_hold_every_layout_file(name):
    """The schemas list the union of the layout files, so a message of any of them passes the schema;
    what belongs to one layout (probs, near) is checked against that layout in check.py."""
    doc = LAYOUTS[name]
    assert {n["id"] for n in doc["nodes"]} <= set(DEFS["node"]["enum"])
    assert {link["id"] for link in doc["links"]} <= set(DEFS["link"]["enum"])
    assert {s["id"] for s in doc["router_spots"]} <= set(DEFS["router_spot"]["enum"])
    assert {n["id"] for n in doc["nodes"] if "receiver" in n["roles"]} <= set(DEFS["receiver"]["enum"])
    zones = [z["id"] for z in doc["zones"]]
    assert zones == list(range(1, len(zones) + 1)) and len(zones) <= DEFS["zone"]["maximum"]
    probs = SCHEMAS["state"]["properties"]["pred"]["properties"]["probs"]
    assert probs["minItems"] <= 1 + len(zones) <= probs["maxItems"]   # [empty, z1, ...]
    rules = {r["if"]["properties"]["link"]["const"]: {k: v["const"] for k, v in r["then"]["properties"].items()}
             for r in SCHEMAS["rssi"]["allOf"]}
    for link in doc["links"]:
        assert link["id"] == f"{link['tx']}>{link['rx']}:{link['kind']}"
        assert rules[link["id"]] == {"tx": link["tx"], "rx": link["rx"], "kind": link["kind"]}
    assert check.errors(doc, "nodes") == []
    presence = doc.get("presence")
    if presence:   # the line that decides, and its second opinion, are lines of this layout that cross the spot
        crossing = {link["id"] for link in doc["links"] if link.get("crosses_spot") is True}
        assert presence["line"] in crossing and presence.get("second", presence["line"]) in crossing


def test_probs_has_one_entry_for_empty_and_one_per_zone_of_the_layout():
    pred = {"present": True, "kind": "person", "zone": 1, "zone_set": [1], "motion": "still", "still_s": 1.0, "why": []}
    for name, doc in LAYOUTS.items():
        right = state("S-home", None, None)
        right["objects"] = []
        n = 1 + len(doc["zones"])
        right["pred"] = {**pred, "probs": [round(1 / n, 3)] * n}
        assert check.errors(right, layout=doc) == [], name
        for wrong in (n - 1, n + 1):
            bad = {**right, "pred": {**pred, "probs": [0.1] * wrong}}
            assert any("$.pred.probs" in e for e in check.errors(bad, layout=doc)), (name, wrong)


def test_the_rssi_schema_pins_tx_rx_and_kind_for_every_link():
    rules = {r["if"]["properties"]["link"]["const"]: {k: v["const"] for k, v in r["then"]["properties"].items()}
             for r in SCHEMAS["rssi"]["allOf"]}
    core = {link["id"]: {"tx": link["tx"], "rx": link["rx"], "kind": link["kind"]} for link in DOC["links"]}
    hall = {link: {"tx": link[0], "rx": link[2:].split(":")[0], "kind": "ble"} for link in HALL_LINKS}
    assert rules == {**core, **hall}


def test_hall_beacons_have_their_own_letters_and_are_never_core():
    beacons = DOC["hall"]["beacons"]
    assert {b["data_hex"]: b["node"] for b in beacons} == HALL_BEACONS
    assert not set(HALL_BEACONS) & set(BEACONS)                       # B is Pi B's, so the hall has H and J
    assert not {b["node"] for b in beacons} & set(NODES)
    assert [n["id"] for n in DOC["nodes"] if "receiver" in n["roles"]] == RECEIVERS == DEFS["receiver"]["enum"]
    assert DEFS["hall_node"]["enum"] == [b["node"] for b in beacons]
    assert DEFS["hall_link"]["enum"] == HALL_LINKS == [f"{b['node']}>{rx}:ble" for rx in RECEIVERS for b in beacons]
    assert not set(HALL_LINKS) & set(LINKS)
    assert "FFFF 52 53 'H' and FFFF 52 53 'J' -> nodes h and j" in SECTION_3


def test_pi_b_links_are_the_ones_section_6_keeps_out_of_blind():
    heard_by_pi_b = [i for i, link in enumerate(DOC["links"], 1) if link["rx"] == "pi5b"]
    assert heard_by_pi_b == [8, 9, 10, 11]
    assert "(rx pi5b: links 8, 9, 10 and 11)" in (REPO / "CONTRACTS.md").read_text(encoding="utf-8")
    assert [i for i, link in enumerate(DOC["links"], 1) if "pi5" in (link["tx"], link["rx"])] == [1, 2, 5, 6, 8, 9, 12]


def test_section_3_says_what_nodes_json_says():
    for n in DOC["nodes"]:
        x, y, z = n["xyz_m"]
        assert re.search(rf"^\s+{n['id']}\s+\({x}, {y}, {z}\)", SECTION_3, re.M), n["id"]
    rows = re.findall(r"^\s+(\d+)\s+(\S+>\S+:\S+)\s+(wifi|ble)\s+(\S+)\s+(\S+)\s", SECTION_3, re.M)
    assert [(int(no), link, kind, tx, rx) for no, link, kind, tx, rx in rows] == \
        [(i, link["id"], link["kind"], link["tx"], link["rx"]) for i, link in enumerate(DOC["links"], 1)]
    assert DOC["zone_rule"].split(";")[0] in SECTION_3
    for zone in DOC["zones"]:
        cx, cy = zone["centre_m"]
        assert f'{zone["id"]} {"West" if zone["side"] == "W" else "East"} "{zone["name"]}", centre ({cx}, {cy})' in SECTION_3
    for spot in DOC["router_spots"] + DOC["tray_spots"]:
        assert f'{spot["id"]} ({", ".join(str(v) for v in spot["xyz_m"])})' in SECTION_3
    assert "<'S' | 'B' | 'E' | 'W'>" in SECTION_3


def test_check_reads_positions_from_nodes_json():
    assert check.NODES == {n["id"]: tuple(n["xyz_m"][:2]) for n in ACTIVE["nodes"]}
    assert check.ROUTER_SPOTS == {s["id"]: tuple(s["xyz_m"][:2]) for s in ACTIVE["router_spots"]}
    assert check.load_layout("desk") == DOC and check.load_layout() == ACTIVE
    assert check._xy(DOC["nodes"]) == {k: v[:2] for k, v in NODES.items()}
    assert check._xy(DOC["router_spots"]) == {k: v[:2] for k, v in ROUTER_SPOTS.items()}


def state(router, xy, near):
    """An untrained state (pred null) with one object, to be checked against a layout."""
    line = (REPO / "contracts" / "fixtures" / "desk" / "valid_state.jsonl").read_text(encoding="utf-8").splitlines()[1]
    return {**json.loads(line), "router": router, "objects": [{"xy_m": xy, "near": near, "since_s": 6.0, "drop_db": 5.1}]}


@pytest.mark.parametrize("router, xy, near, ok", [
    ("S-home", [0.86, 1.0], "pi5", True),     # the tray at T1, next to Pi A
    ("S-home", [0.86, 1.0], "pi5b", False),
    ("S-home", [0.45, 0.9], "pi5b", True),    # Pi B is 0.30 m away, Pi A at home 0.40 m
    ("S-W30", [0.45, 0.9], "pi5", True),      # the router moved west, to 0.21 m away: now it is the closest
    ("S-W30", [0.45, 0.9], "pi5b", False),
    ("S-home", [1.35, 1.05], None, True),     # more than 0.5 m from every node
    ("S-E30", [1.35, 1.05], "pi5", True),     # the router moved east, to 0.25 m away
])
def test_near_follows_the_router_to_its_spot(router, xy, near, ok):
    found = [e for e in check.errors(state(router, xy, near), layout=DOC) if ".near" in e]
    assert (found == []) is ok, found


@pytest.mark.parametrize("xy, near, ok", [
    ([0.4, 0.2], "pi5b", True),      # on the spot, 0.4 m from Pi B
    ([0.4, 0.2], None, False),
    ([0.4, 0.78], "unoq", True),     # at the desk's edge: the board is 4.5 cm away, Pi A the same, and a tie is the board's
    ([0.36, 0.78], "pi5", True),
    ([0.4, 0.2], "east", False),     # no such device on the gate
])
def test_near_is_judged_on_the_layout_the_state_belongs_to(xy, near, ok):
    found = [e for e in check.errors(state("S-home", xy, near), layout=LAYOUTS["gate"]) if ".near" in e]
    assert (found == []) is ok, found


def test_section_3_has_the_gate_layout_too():
    gate = LAYOUTS["gate"]
    for n in gate["nodes"]:
        assert f'{n["id"]} ({", ".join(str(v) for v in n["xyz_m"])})' in SECTION_3, n["id"]
    assert ", ".join(link["id"] for link in gate["links"]) in SECTION_3
    zone = gate["zones"][0]
    assert f'{zone["id"]} "{zone["name"]}", centre ({zone["centre_m"][0]}, {zone["centre_m"][1]}), still_alert_s {zone["still_alert_s"]}' in SECTION_3
    assert "python -m radio.use_layout <name>" in SECTION_3 and '"crosses_spot": true | false' in SECTION_3
    assert "gate-3 (radio/layouts/gate-3.json)" in SECTION_3 and len(LAYOUTS["gate-3"]["links"]) == 3


def test_nodes_are_far_enough_apart_for_near_to_mean_something():
    xy = {k: v[:2] for k, v in NODES.items()}
    assert min(math.dist(xy[a], xy[b]) for a in xy for b in xy if a < b) > 0.5
