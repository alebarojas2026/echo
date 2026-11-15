import pytest

from sim import fake

NAMES = ["zone_tour", "stand_still", "empty_room", "metal_object",
         "wave_checkin", "tray_t1", "router_move", "dropped_link", "camera_unplug", "clipped_feet", "demo", "still_flicker", "tray_removed", "lesson"]


def labels(name):
    return [e for e in fake.simulate(fake.load_path(name)) if e["type"] == "label"]


def test_all_paths_are_on_disk():
    assert sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_path_stays_inside_the_square(name):
    path = fake.load_path(name)
    assert path["name"] == name and path["duration_s"] > 0
    times = [w["t"] for w in path["person"] or []]
    assert times == sorted(times) and all(t <= path["duration_s"] for t in times)
    for w in path["person"] or []:
        if w["x"] is not None:
            assert 0 <= w["x"] <= fake.SIZE and 0 <= w["y"] <= fake.SIZE


def test_zone_tour_stands_in_every_zone():
    order = []
    for e in labels("zone_tour"):
        if e["present"] and e["motion"] == "still" and order[-1:] != [e["zone"]]:
            order.append(e["zone"])
    assert order == [3, 4, 2, 1]
    assert labels("zone_tour")[-1]["present"] is False


def test_stand_still_is_still_for_15_seconds():
    still = [e for e in labels("stand_still") if e["motion"] == "still"]
    assert 14.5 <= still[-1]["t"] - still[0]["t"] <= 15.5
    assert {e["zone"] for e in still} == {4}  # Bathroom: the 10 s alert zone


@pytest.mark.parametrize("name", ["empty_room", "metal_object", "tray_t1", "router_move"])
def test_nobody_home(name):
    assert not any(e["present"] or e["motion"] for e in labels(name))
    assert {e["zone"] for e in labels(name)} == {0}


def test_metal_object_drops_only_the_links_of_its_node():
    path = fake.load_path("metal_object")
    assert path["label_mode"] == "object"
    events = list(fake.simulate(path))
    assert events[0]["purpose"] == "object"
    for link in fake.LINKS:
        values = [e["dbm"] for e in events if e.get("link") == fake.link_id(*link)]
        loss = fake.baseline(*link) - sum(values) / len(values)
        early = sum(values[:150]) / 150
        late = sum(values[-150:]) / 150
        assert abs(early - late) < 0.5  # never moves
        assert (loss > 3) == ("east" in link)


def test_cli_accepts_a_short_name(capsys):
    fake.main(["empty_room", "--fast"])
    assert len(capsys.readouterr().out.splitlines()) == 1 + 30 * 15 * 6 + 30 * 15 // 2 + 30  # meta, rssi, labels, cam
