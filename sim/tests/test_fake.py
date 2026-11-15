import io
import json
from statistics import mean

import pytest

from sim import fake
from sim.wire import encoder


@pytest.fixture(autouse=True)
def _on_the_square(square):
    """These tests check rules with the square's points and numbers, so they pin the square
    (sim/tests/conftest.py) whichever layout radio/nodes.json holds."""


DIAGONAL = {1: "west>unoq:ble", 2: "east>unoq:ble", 3: "west>pi5:ble", 4: "east>pi5:ble"}
CENTRES = {1: (0.5, 1.5), 2: (1.5, 1.5), 3: (0.5, 0.5), 4: (1.5, 0.5)}


def path(person=None, objects=None, duration=4, **extra):
    return {"duration_s": duration, "person": person, "objects": objects, **extra}


def still(x, y):
    return [{"t": 0, "x": x, "y": y}]


def of(events, type_):
    return [e for e in events if e["type"] == type_]


def avg_dbm(events, link):
    return mean(e["dbm"] for e in of(events, "rssi") if e["link"] == link)


def base(link):
    return next(fake.baseline(*l) for l in fake.LINKS if fake.link_id(*l) == link)


def test_contract_links_at_requested_rate():
    events = list(fake.simulate(path(duration=2), rate=15))
    rssi = of(events, "rssi")
    assert {e["link"] for e in rssi} == {
        "pi5>unoq:wifi", "pi5>unoq:ble", "east>unoq:ble", "west>unoq:ble", "east>pi5:ble", "west>pi5:ble"}
    assert all(e["link"] == f'{e["tx"]}>{e["rx"]}:{e["kind"]}' for e in rssi)
    assert len(rssi) == 6 * 15 * 2
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)


def test_contract_zones():
    assert {z: fake.zone_of(*xy) for z, xy in CENTRES.items()} == {1: 1, 2: 2, 3: 3, 4: 4}
    assert fake.zone_of(1.0, 1.0) == 2  # x >= 1 is east, y < 1 is south


def test_empty_room_sits_at_baseline_with_noise():
    events = list(fake.simulate(path(duration=10)))
    for link in DIAGONAL.values():
        values = [e["dbm"] for e in of(events, "rssi") if e["link"] == link]
        assert abs(mean(values) - base(link)) < 0.5
        assert len(set(values)) > 1  # noisy, not a flat line
    assert avg_dbm(events, "pi5>unoq:wifi") - avg_dbm(events, "pi5>unoq:ble") > 10


def test_each_zone_blocks_only_its_own_diagonal():
    empty = list(fake.simulate(path()))
    for zone, xy in CENTRES.items():
        events = list(fake.simulate(path(still(*xy))))
        for z, link in DIAGONAL.items():
            lost = avg_dbm(empty, link) - avg_dbm(events, link)
            assert (lost > 6) if z == zone else (abs(lost) < 1)


def test_person_in_the_middle_blocks_both_pi5_unoq_links():
    empty, mid = list(fake.simulate(path())), list(fake.simulate(path(still(1.0, 1.0))))
    for link in ("pi5>unoq:wifi", "pi5>unoq:ble"):
        assert avg_dbm(empty, link) - avg_dbm(mid, link) > 6


def test_labels_follow_the_person():
    walk = [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 2, "x": 1.5, "y": 1.5},
            {"t": 5, "x": 1.5, "y": 1.5}, {"t": 6, "x": None}]
    labels = of(fake.simulate(path(walk, duration=8)), "label")
    at = lambda t: min(labels, key=lambda e: abs(e["t"] - t))
    assert at(0)["motion"] == "moving"  # walking from the very first frame
    first = at(0.4)
    assert (first["zone"], first["present"], first["persons_in_frame"], first["motion"]) == (3, True, 1, "moving")
    assert first["foot_m"] == [0.7, 0.7] and first["mode"] == "person" and first["clipped"] is False
    assert 0 <= first["conf"] <= 1
    assert (at(4.5)["zone"], at(4.5)["motion"], at(4.5)["foot_m"]) == (2, "still", [1.5, 1.5])
    gone = at(7)
    assert (gone["present"], gone["zone"], gone["foot_m"], gone["persons_in_frame"]) == (False, 0, None, 0)
    assert 5 <= len(labels) / 8 <= 10  # contract: 5-10 labels a second
    assert [e["frame"] for e in labels] == list(range(len(labels)))


def test_slow_drift_is_not_moving():
    creep = [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 10, "x": 1.5, "y": 0.5}]  # 0.1 m/s
    labels = of(fake.simulate(path(creep, duration=10)), "label")
    assert {e["motion"] for e in labels} == {"still"}


def test_meta_first_then_cam_every_second():
    events = list(fake.simulate(path(duration=3, name="x", meta={"purpose": "train"})))
    assert events[0] == {"type": "meta", "t": 0.0, "session": "sim-x", "purpose": "train", "walker": "sim"}
    cams = of(events, "cam")
    assert [e["t"] for e in cams] == [0.0, 1.0, 2.0]
    assert all(e["state"] == "on" and 5 <= e["fps"] <= 10 for e in cams)


def test_static_object_gives_a_steady_drop_and_no_person():
    metal = [{"x": 1.0, "y": 0.15, "drop_db": 6}]  # next to pi5
    events = list(fake.simulate(path(objects=metal, duration=10, label_mode="object")))
    empty = list(fake.simulate(path(duration=10)))
    first = [e for e in events if e["t"] < 5]
    second = [e for e in events if e["t"] >= 5]
    for link in ("pi5>unoq:wifi", "east>pi5:ble", "west>pi5:ble"):
        assert avg_dbm(empty, link) - avg_dbm(events, link) > 3
        assert abs(avg_dbm(first, link) - avg_dbm(second, link)) < 0.5
    assert abs(avg_dbm(empty, "east>unoq:ble") - avg_dbm(events, "east>unoq:ble")) < 1
    labels = of(events, "label")
    assert not any(e["present"] or e["persons_in_frame"] for e in labels)
    assert {e["mode"] for e in labels} == {"object"}


def test_same_seed_same_data():
    p = path(still(1.5, 0.5))
    assert list(fake.simulate(p, seed=7)) == list(fake.simulate(p, seed=7))
    assert list(fake.simulate(p, seed=7)) != list(fake.simulate(p, seed=8))


def test_pace_waits_for_each_timestamp():
    now, out = [100.0], io.StringIO()

    def sleep(s):
        now[0] += s

    fake.pace([(5.0, "a"), (5.5, "b"), (7.0, "c")], out=out, clock=lambda: now[0], sleep=sleep)
    assert out.getvalue() == "a\nb\nc\n"
    assert abs(now[0] - 102.0) < 1e-9  # 2 s of data took 2 s
    fake.pace([(0, "a"), (4, "b")], out=out, speed=4, clock=lambda: now[0], sleep=sleep)
    assert abs(now[0] - 103.0) < 1e-9


def test_cli_fast_prints_contract_lines(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(path(still(0.5, 1.5), duration=1)))
    fake.main([str(f), "--fast", "--rate", "10", "--start-ms", "1763149500000"])
    msgs = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert len(msgs) == 1 + 60 + 10 + 1  # meta, rssi, labels (10 fps at this rate), cam
    assert msgs[0]["t"] == 1763149500000 and msgs[-1]["t"] == 1763149500900
    assert [m["seq"] for m in msgs] == list(range(1, len(msgs) + 1))


# ---- the desk strip: 0.6-1.2 m links, so the person's own width counts (sim/layout.py) ----

CROSSING = {1: ("west>unoq:ble", "west>pi5b:ble"), 2: ("east>unoq:ble", "east>pi5b:ble")}
OVER_THE_DESK = ("pi5>unoq:wifi", "pi5>unoq:ble", "pi5>pi5b:wifi", "pi5>pi5b:ble", "pi5b>pi5:ble")


def test_on_the_strip_a_zone_centre_drops_its_crossing_links_and_not_the_desk_links(strip):
    for zone, centre in strip.centres.items():
        drops = {fake.link_id(*l): fake.person_drop(centre, strip.nodes[l[0]], strip.nodes[l[1]]) for l in fake.LINKS}
        assert all(drops[link] >= 4 for link in CROSSING[zone]), (zone, drops)
        assert all(drops[link] <= 1 for link in OVER_THE_DESK), (zone, drops)
        other = CROSSING[3 - zone]
        assert all(drops[link] <= 1 for link in other), (zone, drops)   # the other side's links stay quiet


def test_on_the_strip_the_feed_shows_those_drops(strip):
    empty = list(fake.simulate(path(duration=6)))
    for zone, centre in strip.centres.items():
        events = list(fake.simulate(path(still(*centre), duration=6)))
        for link in CROSSING[zone]:
            assert avg_dbm(empty, link) - avg_dbm(events, link) > 3.5, (zone, link)
        for link in OVER_THE_DESK:
            assert abs(avg_dbm(empty, link) - avg_dbm(events, link)) < 1.2, (zone, link)
