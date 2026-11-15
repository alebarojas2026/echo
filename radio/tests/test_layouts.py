"""radio/layouts/: every layout file is one the system can run on, and switching is one command.

A layout file is a whole radio/nodes.json. These tests hold for every file in the folder, so a
new layout needs no edit here.
"""
import json
from pathlib import Path

import pytest

from contracts import check
from radio import use_layout

REPO = Path(__file__).resolve().parents[2]
NAMES = use_layout.names()


def doc(name):
    return json.loads((use_layout.LAYOUTS / f"{name}.json").read_text(encoding="utf-8"))


def test_there_is_a_desk_and_a_gate_layout_and_one_of_them_is_active():
    assert {"desk", "gate", "gate-3"} <= set(NAMES)
    assert use_layout.active() in NAMES   # radio/nodes.json is always a copy of a layout file


@pytest.mark.parametrize("name", NAMES)
def test_every_layout_file_is_a_layout_and_passes_the_schema(name):
    assert use_layout.problems(doc(name)) == []
    assert check.errors(doc(name), "nodes") == []
    assert doc(name)["layout"] == name


@pytest.mark.parametrize("name", NAMES)
def test_zone_centres_lie_in_their_zone_and_the_rule_says_so(name):
    d = doc(name)
    w, h = d["frame"]["strip_m"]
    split = d["frame"].get("zone_split_x_m")
    for zone in d["zones"]:
        x, y = zone["centre_m"]
        assert 0 <= x <= w and 0 <= y <= h
        assert zone["id"] == (1 if split is None else 1 + (x >= split))
    assert f"0 <= x <= {w} and 0 <= y <= {h}" in d["zone_rule"]


@pytest.mark.parametrize("name", NAMES)
def test_the_x_ray_grid_is_whole_cells_of_an_eighth_of_a_metre(name):
    # Section 6: size_m plus 0.2 m each side, in 0.125 m cells. The brain and the fake feed must cut the same grid.
    for side in doc(name)["frame"]["size_m"]:
        cells = (side + 0.4) / 0.125
        assert abs(cells - round(cells)) < 1e-9, side


def test_the_gate_is_three_devices_six_links_and_one_spot():
    d = doc("gate")
    assert [n["id"] for n in d["nodes"]] == ["unoq", "pi5", "pi5b"]
    assert [n["device"] for n in d["nodes"]] == ["unoq", "pi5", "pi5"]
    assert [link["id"] for link in d["links"]] == ["pi5>unoq:wifi", "pi5>unoq:ble", "pi5b>unoq:ble",
                                                   "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble"]
    # the lines a person on the spot stands in are the ones to or from Pi B
    assert [link["id"] for link in d["links"] if link["crosses_spot"]] == \
        [link["id"] for link in d["links"] if "pi5b" in (link["tx"], link["rx"])]
    assert d["zones"] == [{"id": 1, "name": "At the desk", "centre_m": [0.4, 0.3], "still_alert_s": 10}]
    assert "zone_split_x_m" not in d["frame"] and d["frame"]["strip_m"] == [0.8, 0.6]
    assert d["armed"] == {"hold_s": 3} and "hall" not in d
    assert [link["id"] for link in d["links"] if link.get("classifier") is False] == ["pi5b>pi5:ble"]
    at = {n["id"]: n["xyz_m"] for n in d["nodes"]}
    assert at["pi5b"][1] < 0 < at["unoq"][1]                       # Pi B and the desk are either side of the spot
    assert abs(at["unoq"][1] - at["pi5b"][1] - 1.0) < 1e-9          # 1.0 m apart
    assert abs(abs(at["unoq"][0] - at["pi5"][0]) - 0.08) < 1e-9     # the board and Pi A, 8 cm apart
    assert {s["id"]: s["xyz_m"] for s in d["router_spots"]}["S-home"] == at["pi5"]


def test_use_copies_the_file_whole(tmp_path):
    target = tmp_path / "nodes.json"
    target.write_text("{}", encoding="utf-8")
    for name in ("gate", "desk"):
        assert use_layout.use(name, target=target) == doc(name)
        assert json.loads(target.read_text(encoding="utf-8")) == doc(name)
        assert use_layout.active(target=target) == name
    assert list(tmp_path.iterdir()) == [target]   # no half-written file is left behind


def test_a_wrong_name_or_a_broken_file_changes_nothing(tmp_path):
    layouts, target = tmp_path / "layouts", tmp_path / "nodes.json"
    layouts.mkdir()
    target.write_text('{"kept": true}', encoding="utf-8")
    bad = doc("gate")
    bad["links"][0]["rx"] = "east"   # a node the file doesn't have
    (layouts / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    (layouts / "torn.json").write_text("{", encoding="utf-8")
    for name in ("nowhere", "bad", "torn"):
        with pytest.raises(ValueError):
            use_layout.use(name, layouts=layouts, target=target)
    assert target.read_text(encoding="utf-8") == '{"kept": true}'


@pytest.mark.parametrize("change, said", [
    (lambda d: d["zones"].append({"id": 3, "name": "x"}), "numbered"),
    (lambda d: d["frame"].pop("strip_m"), "strip_m"),
    (lambda d: d["links"][2].update(crosses_spot="yes"), "crosses_spot"),
    (lambda d: d["beacons"]["payloads"].pop(), "beacon payload"),
    (lambda d: d["nodes"][0].update(roles=["beacon"]), "not a receiver"),
])
def test_problems_are_said_in_plain_words(change, said):
    d = doc("gate")
    change(d)
    assert any(said in p for p in use_layout.problems(d))


def test_the_command_says_what_it_did(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(use_layout, "ACTIVE", tmp_path / "nodes.json")
    monkeypatch.setattr(use_layout.use, "__defaults__", (use_layout.LAYOUTS, tmp_path / "nodes.json"))
    assert use_layout.main(["gate"]) == 0
    assert "3 devices, 6 links, 1 zone." in capsys.readouterr().out
    assert use_layout.main(["nope"]) == 1
    assert "no layout called 'nope'" in capsys.readouterr().err


def test_gate_3_is_the_gate_with_the_three_lines_that_cross_the_spot():
    d, gate = doc("gate-3"), doc("gate")
    assert [link["id"] for link in d["links"]] == ["pi5>pi5b:wifi", "pi5b>unoq:ble", "pi5b>pi5:ble"]
    assert all(link["crosses_spot"] for link in d["links"])
    for key in ("frame", "nodes", "zones", "zone_rule", "router_spots", "tray_spots", "armed", "beacons", "presence",
                "presence_note"):
        assert d[key] == gate[key]                       # the same place and the same devices, fewer lines


def test_on_the_gate_the_wifi_line_to_pi_b_decides_and_pi_bs_roles_keep_it_alive():
    for name in ("gate", "gate-3"):
        d = doc(name)
        links = {link["id"]: link for link in d["links"]}
        # on_db, off_db and moving_spread_db are the values chosen from the kit's recordings (the note in the file
        # says how). A change to one of them is a new choice from recordings, not an edit.
        assert d["presence"] == {"line": "pi5>pi5b:wifi", "second": "pi5b>unoq:ble", "on_db": 7, "off_db": 3, "second_hold_s": 5,
                                 "object_db": 3, "object_max_db": 10, "object_spread_db": 1.0, "object_hold_s": 3,
                                 "moving_spread_db": 2.5, "still_spread_db": 1.5, "motion_hold_s": 1.5,
                                 "checkin_return_s": 8}
        assert d["presence"]["still_spread_db"] < d["presence"]["moving_spread_db"]
        assert d["armed"] == {"hold_s": 3}               # the walk-throughs on the kit were all gone well inside it
        # a thing in the line is shallower than any person seen on the kit (13.5 dB), and off_db < on_db < that.
        # Somebody is let go where a thing's range begins (off_db is object_db), never under it.
        assert d["presence"]["object_db"] <= d["presence"]["off_db"] < d["presence"]["on_db"] < d["presence"]["object_max_db"] < 13.5
        assert d["presence"]["object_spread_db"] < d["presence"]["moving_spread_db"]
        # no older flag may switch the line that decides off: it is a classifier link, and so is its second opinion
        assert not any(link.get("classifier") is False for link in d["links"]
                       if link["id"] in (d["presence"]["line"], d["presence"]["second"]))
        assert links["pi5>pi5b:wifi"]["crosses_spot"] is True and links["pi5>pi5b:wifi"].get("classifier", True) is True
        assert links["pi5b>pi5:ble"]["classifier"] is False                    # unreliable on the kit: it never votes
        roles = {n["id"]: n["roles"] for n in d["nodes"]}
        assert "receiver" in roles["pi5b"] and "router" in roles["pi5"]        # Pi B reads the hotspot's signal: never a beacon only
    assert doc("gate")["links"][0]["crosses_spot"] is False                    # pi5>unoq:wifi crosses nothing
