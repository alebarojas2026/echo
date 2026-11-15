"""The sim on a layout with one zone and three devices (layouts/spot.json, the gate layout)."""
import json

from sim import fake, lesson, state
from sim.tests.conftest import LAYOUTS, load, pin


def test_one_zone_covers_the_strip_and_nothing_else():
    lay = load("spot")
    assert lay.zones == {1: 10} and lay.split_x_m is None and lay.names == {1: "At the desk"}
    assert [lay.zone_of(x, y) for x, y in ((0.4, 0.3), (0.0, 0.0), (0.8, 0.6))] == [1, 1, 1]
    assert [lay.zone_of(x, y) for x, y in ((0.4, -0.1), (0.4, 0.7), (-0.1, 0.3), (0.9, 0.3))] == [0, 0, 0, 0]
    assert lay.tour() == [1] and lay.still_zone() == 1 and lay.calm_zone() == 1     # nowhere else to stand
    assert lay.nodes["pi5b"] == (0.4, -0.2)                                         # a device outside frame.size_m
    assert lay.grid == {"w": 10, "h": 14, "cell_m": 0.125, "origin_m": [-0.2, -0.2]}


def test_the_device_that_gets_unplugged_follows_the_layout():
    assert load("spot").prop_node() == "pi5b"       # the far device: no east beacon here
    assert load("strip").prop_node() == "east" and load("square").prop_node() == "east"
    path = load("spot").resolve({"outages": [{"node": "prop", "t_on": 1, "t_off": 2}], "objects": [{"near": "prop"}]})
    assert path["outages"] == [{"node": "pi5b", "t_on": 1, "t_off": 2}] and path["objects"][0]["y"] == -0.2


def test_every_path_file_plays_on_one_spot_with_six_links_and_one_zone(monkeypatch):
    pin(monkeypatch, "spot")
    for file in sorted(fake.PATHS_DIR.glob("*.json")):
        events = list(fake.simulate(fake.load_path(str(file)), seed=1))
        links = {e["link"] for e in events if e["type"] == "rssi" and e["tx"] not in ("h", "j")}
        assert links <= {"pi5>unoq:wifi", "pi5>unoq:ble", "pi5b>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble"}, file.name
        assert {e["zone"] for e in events if e["type"] == "label"} <= {0, 1, None}, file.name


def test_a_person_on_the_spot_drops_the_lines_to_pi_b_and_not_the_desks(monkeypatch):
    lay = pin(monkeypatch, "spot")
    at = lay.centres[1]
    drops = {fake.link_id(tx, rx, kind): fake.person_drop(at, lay.nodes[tx], lay.nodes[rx]) for tx, rx, kind in lay.links}
    assert all(drops[k] > 6 for k in drops if "pi5b" in k) and all(drops[k] < 1 for k in drops if "pi5b" not in k)


def test_the_lesson_on_one_spot_has_no_sides_and_no_dead_band(monkeypatch):
    lay = pin(monkeypatch, "spot")
    path = lesson.path(lay)
    assert path["dead_band_m"] == 0.0 and "left" not in path["about"] and "right" not in path["about"]
    assert {zone for _, _, zone in lesson.stands(lay)} == {1}
    labels = [e for e in fake.simulate(path, seed=2) if e["type"] == "label"]
    assert not any(e["clipped"] for e in labels) and {e["zone"] for e in labels} == {0, 1}
    assert all(e["foot_m"] is None for e in labels)                                  # the desk view has no foot point
    doc = json.loads((LAYOUTS / "spot.json").read_text(encoding="utf-8"))
    assert "zone_split_x_m" not in doc["frame"] and len(doc["zones"]) == 1


def test_on_the_gate_the_fake_brain_never_says_move_the_router(monkeypatch):
    lay = pin(monkeypatch, "spot")
    assert lay.presence_line == "pi5>pi5b:wifi"
    for name in ("tray_t1", "router_move", "demo"):
        msgs = list(state.run(fake.load_path(name)))
        states = [m for m in msgs if m["type"] == "state"]
        assert states and all(m["advice"] is None for m in states), name
        assert not any(m["type"] == "event" and m["kind"] == "advice" for m in msgs), name


def test_the_presence_line_drops_as_far_as_it_did_on_the_kit(monkeypatch):
    lay = pin(monkeypatch, "spot")
    events = list(fake.simulate({"name": "stand", "duration_s": 6, "person": [{"t": 0, "x": 0.4, "y": 0.3}]}, seed=1, noise_db=0.0))
    level = lambda link: sorted(e["dbm"] for e in events if e["type"] == "rssi" and e["link"] == link)[0]   # noqa: E731
    empty = {fake.link_id(tx, rx, kind): round(fake.baseline(tx, rx, kind)) for tx, rx, kind in lay.links}
    assert 15 <= empty["pi5>pi5b:wifi"] - level("pi5>pi5b:wifi") <= 21
    assert 6 <= empty["pi5b>unoq:ble"] - level("pi5b>unoq:ble") <= 9
