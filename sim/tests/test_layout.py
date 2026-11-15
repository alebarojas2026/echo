"""The fake feed's layout comes from radio/nodes.json."""
from sim import fake, layout, state


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
        "zones": [{"id": 1, "name": "Living room", "still_alert_s": None}, {"id": 2, "name": "Bathroom", "still_alert_s": 10}]})
    assert desk.grid == {"w": 16, "h": 12, "cell_m": 0.125, "origin_m": [-0.2, -0.2]}   # section 6 of the draft
    assert [desk.zone_of(*p) for p in ((0.4, 0.3), (1.2, 0.3), (0.8, 0.0), (1.2, 0.8), (1.7, 0.3))] == [1, 2, 2, 0, 0]
    assert desk.zones == {1: None, 2: 10} and desk.nodes["pi5"] == (0.8, 1.1)
