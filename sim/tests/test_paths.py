import pytest

from sim import fake

NAMES = ["zone_tour", "stand_still", "empty_room", "metal_object",
         "wave_checkin", "tray_t1", "router_move", "dropped_link", "camera_unplug", "clipped_feet", "demo", "still_flicker", "tray_removed", "arrival", "tamper", "passed_by", "step_in"]


def labels(name):
    return [e for e in fake.simulate(fake.load_path(name)) if e["type"] == "label"]


def test_all_paths_are_on_disk():
    assert sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_path_stays_in_the_area_or_just_past_an_end(name, each_layout):
    path = fake.load_path(name)
    assert path["name"] == name and path["duration_s"] > 0
    times = [w["t"] for w in path["person"] or []]
    assert times == sorted(times) and all(t <= path["duration_s"] for t in times)
    w_m, h_m = each_layout.strip_m or each_layout.size_m
    for w in path["person"] or []:
        if w["x"] is not None:   # inside, or walking in or out 0.4 m past an end, level with a zone
            assert -0.4 <= w["x"] <= w_m + 0.4 and 0 <= w["y"] <= h_m, (name, w)
            assert 0 <= w["x"] <= w_m or w["y"] in {c[1] for c in each_layout.centres.values()}, (name, w)


def test_zone_tour_stands_in_every_zone(each_layout):
    order = []
    for e in labels("zone_tour"):
        if e["present"] and e["motion"] == "still" and order[-1:] != [e["zone"]]:
            order.append(e["zone"])
    tour = each_layout.tour()
    assert order == [tour[i % len(tour)] for i in range(4)]   # the square: 3, 4, 2, 1; the strip: 1, 2, 1, 2
    assert set(order) == set(each_layout.zones)
    assert labels("zone_tour")[-1]["present"] is False


def test_walking_in_past_the_end_is_in_frame_but_not_present(each_layout):
    first = labels("zone_tour")[0]
    assert (first["persons_in_frame"], first["present"], first["zone"], first["foot_m"]) == (1, False, 0, None)


def test_stand_still_is_still_for_15_seconds(each_layout):
    still = [e for e in labels("stand_still") if e["motion"] == "still"]
    assert 14.5 <= still[-1]["t"] - still[0]["t"] <= 15.5
    assert {e["zone"] for e in still} == {each_layout.still_zone()}   # the square: 4 Bathroom, 10 s
    assert each_layout.zones[each_layout.still_zone()] == 10


@pytest.mark.parametrize("name", ["empty_room", "metal_object", "tray_t1", "router_move"])
def test_nobody_home(name, each_layout):
    assert not any(e["present"] or e["motion"] for e in labels(name))
    assert {e["zone"] for e in labels(name)} == {0}


def test_metal_object_drops_only_the_links_of_its_node(each_layout):
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
    n = len(fake.LINKS)   # the layout in radio/nodes.json: 6 links on the square, 12 on the strip
    assert len(capsys.readouterr().out.splitlines()) == 1 + 30 * 15 * n + 30 * 15 // 2 + 30  # meta, rssi, labels, cam
