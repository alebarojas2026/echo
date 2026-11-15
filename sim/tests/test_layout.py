"""The fake feed's layout comes from radio/nodes.json."""
import pytest

from sim import fake, layout, state

square = pytest.mark.skipif(layout.LAYOUT.strip_m is not None, reason="radio/nodes.json is the desk strip")


@square
def test_mains_nodes_json_is_the_square_the_sim_always_used():
    assert fake.NODES == {"unoq": (1.0, 2.0), "pi5": (1.0, 0.0), "east": (2.0, 1.0), "west": (0.0, 1.0)}
    assert fake.LINKS[0] == ("pi5", "unoq", "wifi") and len(fake.LINKS) == 6
    assert fake.ROUTER_SPOTS["S-W30"] == (0.7, 0.0)
    assert state.STILL_ALERT_S == {1: 60, 2: None, 3: None, 4: 10}
    assert state.GRID == {"w": 10, "h": 10, "cell_m": 0.24, "origin_m": [-0.2, -0.2]}
    assert [fake.zone_of(*p) for p in ((0.5, 1.5), (1.5, 1.5), (0.5, 0.5), (1.5, 0.5))] == [1, 2, 3, 4]


def test_the_desk_strip():
    desk = layout.Layout({
        "frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8},
        "nodes": [{"id": "unoq", "xyz_m": [1.1, 0.6, 1.0]}, {"id": "pi5", "xyz_m": [0.8, 1.1, 1.0]}],
        "links": [{"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq", "kind": "wifi"}],
        "router_spots": [{"id": "S-home", "xyz_m": [0.8, 1.1, 1.0]}],
        "tray_spots": [{"id": "T1", "xyz_m": [0.86, 1.0, 1.0]}],
        "zones": [{"id": 1, "name": "Living room", "centre_m": [0.4, 0.3], "still_alert_s": None},
                  {"id": 2, "name": "Bathroom", "centre_m": [1.2, 0.3], "still_alert_s": 10}]})
    assert desk.centres == {1: (0.4, 0.3), 2: (1.2, 0.3)} and desk.tray == (0.86, 1.0)
    assert desk.grid == {"w": 16, "h": 12, "cell_m": 0.125, "origin_m": [-0.2, -0.2]}   # section 6 of the draft
    assert [desk.zone_of(*p) for p in ((0.4, 0.3), (1.2, 0.3), (0.8, 0.0), (1.2, 0.8), (1.7, 0.3))] == [1, 2, 2, 0, 0]
    assert desk.zones == {1: None, 2: 10} and desk.nodes["pi5"] == (0.8, 1.1)
    assert (desk.tour(), desk.still_zone(), desk.calm_zone()) == ([1, 2], 2, 1)


@square
def test_rehearsal_parts_on_the_square():
    lay = layout.LAYOUT
    assert lay.centres == {1: (0.5, 1.5), 2: (1.5, 1.5), 3: (0.5, 0.5), 4: (1.5, 0.5)} and lay.tray == (1.0, 0.2)
    assert (lay.tour(), lay.still_zone(), lay.calm_zone()) == ([3, 4, 2, 1], 4, 3)


STRIP = {
    "frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8},
    "nodes": [{"id": "unoq", "xyz_m": [1.1, 0.6, 1.0]}, {"id": "pi5", "xyz_m": [0.8, 1.1, 1.0]},
              {"id": "east", "xyz_m": [1.6, 0.25, 1.0]}, {"id": "west", "xyz_m": [0.0, 0.25, 1.0]}],
    "links": [{"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq", "kind": "wifi"}],
    "router_spots": [{"id": "S-home", "xyz_m": [0.8, 1.1, 1.0]}],
    "tray_spots": [{"id": "T1", "xyz_m": [0.86, 1.0, 1.0]}],
    "zones": [{"id": 1, "name": "Left", "centre_m": [0.4, 0.3], "still_alert_s": 10},
              {"id": 2, "name": "Right", "centre_m": [1.2, 0.3], "still_alert_s": 10}]}


def test_zone_relative_paths_resolve_on_each_layout():
    path = {"person": [{"t": 0, "x": None}, {"t": 1, "zone": 1, "outside": "west"}, {"t": 2, "zone": 1, "edge": "west"},
                       {"t": 3, "zone": 2, "dx": 0.1}, {"t": 4, "x": 0.5, "y": 0.5}],
            "objects": [{"spot": "T1", "drop_db": 10}, {"near": "east", "drop_db": 6}]}
    strip = layout.Layout(STRIP).resolve(path)
    assert [(p.get("x"), p.get("y")) for p in strip["person"]] == [(None, None), (-0.4, 0.3), (0.0, 0.3), (1.3, 0.3), (0.5, 0.5)]
    assert [(o["x"], o["y"]) for o in strip["objects"]] == [(0.86, 1.0), (1.45, 0.25)]
    assert layout.Layout(STRIP).zone_of(-0.4, 0.3) == 0                       # past the end: nobody in the area
    square = layout.LAYOUT.resolve({"person": [{"t": 0, "zone": 3, "edge": "west"}, {"t": 1, "zone": 4}],
                                    "objects": [{"near": "east", "drop_db": 6}]})
    if layout.LAYOUT.strip_m is None:   # main's square: the points the old paths wrote in metres
        assert [(p["x"], p["y"]) for p in square["person"]] == [(0.0, 0.5), (1.5, 0.5)]
        assert (square["objects"][0]["x"], square["objects"][0]["y"]) == (1.85, 1.0)


def test_someone_past_the_end_is_not_present():
    from sim import fake
    w = layout.LAYOUT.area_width()
    path = {"name": "t", "duration_s": 3, "person": [{"t": 0, "x": w + 0.4, "y": 0.3}, {"t": 3, "x": w + 0.4, "y": 0.3}]}
    labels = [e for e in fake.simulate(path) if e["type"] == "label"]
    assert labels and all(l["persons_in_frame"] == 1 and l["present"] is False and l["zone"] == 0
                          and l["foot_m"] is None and l["motion"] is None for l in labels)
