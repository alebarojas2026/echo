import pytest

from sim import fake

NAMES = ["zone_tour", "stand_still", "empty_room", "metal_object"]


def labels(name):
    return [e for e in fake.simulate(fake.load_path(name)) if e["kind"] == "label"]


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
        if e["present"] and not e["moving"] and order[-1:] != [e["zone"]]:
            order.append(e["zone"])
    assert order == [0, 1, 3, 2]
    assert labels("zone_tour")[-1]["present"] is False


def test_stand_still_is_still_for_15_seconds():
    still = [e["t"] for e in labels("stand_still") if e["present"] and not e["moving"]]
    assert 14.5 <= max(still) - min(still) <= 15.5
    assert {e["zone"] for e in labels("stand_still") if not e["moving"] and e["present"]} == {3}


@pytest.mark.parametrize("name", ["empty_room", "metal_object"])
def test_nobody_home(name):
    assert not any(e["present"] or e["moving"] for e in labels(name))


def test_metal_object_drops_only_the_links_of_its_node():
    events = list(fake.simulate(fake.load_path("metal_object")))
    for a, b in fake.LINKS:
        values = [e["rssi"] for e in events if e.get("link") == f"{a}-{b}"]
        loss = fake.baseline(a, b) - sum(values) / len(values)
        early = sum(values[:150]) / 150
        late = sum(values[-150:]) / 150
        assert abs(early - late) < 0.5  # never moves
        assert (loss > 3) == ("n1" in (a, b))


def test_cli_accepts_a_short_name(capsys):
    fake.main(["empty_room", "--fast"])
    assert len(capsys.readouterr().out.splitlines()) == 30 * 15 * 6 + 30 * 5
