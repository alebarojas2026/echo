import io
import json
from statistics import mean

from sim import fake
from sim.wire import encode, time_of


def path(person=None, objects=None, duration=4):
    return {"duration_s": duration, "person": person, "objects": objects}


def still(x, y):
    return [{"t": 0, "x": x, "y": y}]


def avg_rssi(events, link):
    return mean(e["rssi"] for e in events if e["kind"] == "rssi" and e["link"] == link)


def test_six_links_at_requested_rate():
    events = list(fake.simulate(path(duration=2), rate=15))
    rssi = [e for e in events if e["kind"] == "rssi"]
    assert len({e["link"] for e in rssi}) == 6
    assert len(rssi) == 6 * 15 * 2
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)


def test_empty_room_sits_at_baseline_with_noise():
    events = list(fake.simulate(path(duration=10)))
    for a, b in fake.LINKS:
        values = [e["rssi"] for e in events if e.get("link") == f"{a}-{b}"]
        assert abs(mean(values) - fake.baseline(a, b)) < 0.5
        assert len(set(values)) > 1  # noisy, not a flat line


def test_person_on_a_link_drops_that_link_only():
    empty = list(fake.simulate(path()))
    blocked = list(fake.simulate(path(still(0.5, 0.5))))  # middle of zone 0, on n0-n3
    assert avg_rssi(empty, "n0-n3") - avg_rssi(blocked, "n0-n3") > 6
    assert abs(avg_rssi(empty, "n1-n2") - avg_rssi(blocked, "n1-n2")) < 1


def test_each_zone_blocks_a_different_link():
    centres = {0: (0.5, 0.5), 1: (1.5, 0.5), 2: (0.5, 1.5), 3: (1.5, 1.5)}
    worst = set()
    for zone, (x, y) in centres.items():
        assert fake.zone_of(x, y) == zone
        events = list(fake.simulate(path(still(x, y))))
        worst.add(max(fake.LINKS, key=lambda l: fake.baseline(*l) - avg_rssi(events, "-".join(l))))
    assert len(worst) == 4


def test_labels_follow_the_person():
    walk = [{"t": 0, "x": 0.5, "y": 0.5}, {"t": 2, "x": 1.5, "y": 1.5},
            {"t": 4, "x": 1.5, "y": 1.5}, {"t": 5, "x": None}]
    labels = [e for e in fake.simulate(path(walk, duration=6)) if e["kind"] == "label"]
    at = lambda t: min(labels, key=lambda e: abs(e["t"] - t))
    assert at(0.4) == {"kind": "label", "t": 0.4, "zone": 0, "present": True, "moving": True}
    assert (at(3.4)["zone"], at(3.4)["moving"]) == (3, False)
    assert at(5.6)["present"] is False and at(5.6)["zone"] is None
    assert 4 <= len(labels) / 6 <= 6  # about 5 labels a second


def test_static_object_gives_a_steady_drop_and_no_person():
    metal = [{"x": 1.0, "y": 0.15, "drop_db": 6}]  # next to n0
    events = list(fake.simulate(path(objects=metal, duration=10)))
    empty = list(fake.simulate(path(duration=10)))
    first = [e for e in events if e["t"] < 5]
    second = [e for e in events if e["t"] >= 5]
    for link in ("n0-n1", "n0-n2", "n0-n3"):
        assert avg_rssi(empty, link) - avg_rssi(events, link) > 3
        assert abs(avg_rssi(first, link) - avg_rssi(second, link)) < 0.5
    assert abs(avg_rssi(empty, "n1-n3") - avg_rssi(events, "n1-n3")) < 1
    assert not any(e["present"] for e in events if e["kind"] == "label")


def test_same_seed_same_data():
    p = path(still(1.5, 0.5))
    assert list(fake.simulate(p, seed=7)) == list(fake.simulate(p, seed=7))
    assert list(fake.simulate(p, seed=7)) != list(fake.simulate(p, seed=8))


def test_wire_lines_are_json_with_a_time():
    for e in fake.simulate(path(still(1, 1), duration=1)):
        line = encode(e)
        assert "\n" not in line
        assert json.loads(line)["type"] in ("rssi", "label")
        assert time_of(line) == e["t"]


def test_pace_waits_for_each_timestamp():
    now, out = [100.0], io.StringIO()

    def sleep(s):
        now[0] += s

    fake.pace([(5.0, "a"), (5.5, "b"), (7.0, "c")], out=out, clock=lambda: now[0], sleep=sleep)
    assert out.getvalue() == "a\nb\nc\n"
    assert abs(now[0] - 102.0) < 1e-9  # 2 s of data took 2 s
    fake.pace([(0, "a"), (4, "b")], out=out, speed=4, clock=lambda: now[0], sleep=sleep)
    assert abs(now[0] - 103.0) < 1e-9


def test_cli_fast_prints_json_lines(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(path(still(0.5, 1.5), duration=1)))
    fake.main([str(f), "--fast", "--rate", "10"])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 60 + 5
    assert all(json.loads(l)["type"] for l in lines)
