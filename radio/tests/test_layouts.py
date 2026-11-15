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


def test_gate_3_is_the_gate_with_pi_b_as_a_beacon_only_and_three_links():
    d, gate = doc("gate-3"), doc("gate")
    assert [link["id"] for link in d["links"]] == ["pi5>unoq:wifi", "pi5b>unoq:ble", "pi5b>pi5:ble"]
    assert [link["id"] for link in d["links"] if link["crosses_spot"]] == ["pi5b>unoq:ble", "pi5b>pi5:ble"]
    assert {n["id"]: n["roles"] for n in d["nodes"]} == {"unoq": ["receiver"], "pi5": ["router", "receiver"], "pi5b": ["beacon"]}
    assert [p["node"] for p in d["beacons"]["payloads"]] == ["pi5b"]
    for key in ("frame", "zones", "zone_rule", "router_spots", "tray_spots", "armed"):
        assert d[key] == gate[key]                       # the same place, fewer lines
    assert [n["xyz_m"] for n in d["nodes"]] == [n["xyz_m"] for n in gate["nodes"]]
