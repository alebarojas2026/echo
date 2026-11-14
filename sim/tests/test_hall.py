"""Hall links in the fake feed and the fake brain (issue #358). Paths without a "hall" block are
untouched; the hall path lives in sim/paths/hall/ so the tests that walk sim/paths/ don't meet it."""
import json

import pytest

from contracts.check import errors
from sim import fake, state
from sim.tests.test_state import UNMEASURED
from sim.wire import encoder

PATH = "hall/hall_walk"
ROW_KEYS = {"id", "tx", "rx", "xy_m", "activity", "moving", "rate_hz", "stale"}
CORE = {fake.link_id(*link) for link in fake.LINKS}


def hall_ids(path):
    return [fake.link_id(tx, rx, "ble") for tx, rx in fake.hall_links(path)]


def states(path):
    return [m for m in state.run(path) if m["type"] == "state"]


def row(s, link):
    return next((r for r in s["hall"] if r["id"] == link), None)


def at(all_states, t):
    return min(all_states, key=lambda s: abs(s["t"] - t))


@pytest.mark.parametrize("name", sorted(p.stem for p in fake.PATHS_DIR.glob("*.json")))
def test_paths_without_a_hall_block_have_no_hall_anywhere(name):
    path = fake.load_path(name)
    assert fake.hall_links(path) == [] and fake.hall_events(path) == []
    assert {e["link"] for e in fake.simulate(path) if e["type"] == "rssi"} <= CORE
    assert not any("hall" in m for m in state.run(path))


def test_a_hall_block_changes_nothing_else_in_the_feed_or_the_state():
    with_hall = fake.load_path(PATH)
    without = {k: v for k, v in with_hall.items() if k != "hall"}
    feed = [e for e in fake.simulate(with_hall) if e.get("link", "") in CORE or e["type"] != "rssi"]
    assert feed == list(fake.simulate(without))
    plain = list(state.run(without))
    stripped = [{k: v for k, v in m.items() if k != "hall"} for m in state.run(with_hall)]
    assert stripped == plain


def test_hall_links_are_every_hall_beacon_heard_by_every_receiver():
    path = fake.load_path(PATH)
    receivers = fake.receivers()
    assert receivers == list(dict.fromkeys(rx for _, rx, _ in fake.LINKS))
    assert fake.hall_links(path) == [(tx, rx) for rx in receivers for tx in ("h", "j")]
    assert not set(hall_ids(path)) & CORE


def test_hall_readings_are_weak_few_and_uneven_and_in_time_order():
    path = fake.load_path(PATH)
    events = list(fake.simulate(path))
    times = [e["t"] for e in events]
    assert times == sorted(times)
    for link in hall_ids(path):
        mine = [e for e in events if e.get("link") == link]
        assert all(e["type"] == "rssi" and e["kind"] == "ble" and link == f'{e["tx"]}>{e["rx"]}:ble' for e in mine)
        quiet = [e for e in mine if e["t"] < 19]
        assert 4 < len(quiet) / 19 < 11                          # about 30% of 22 adverts a second
        gaps = [b["t"] - a["t"] for a, b in zip(quiet, quiet[1:])]
        assert max(gaps) > 4 * min(gaps)                         # uneven, not a steady beat
        core = fake.baseline("east", "unoq", "ble")
        assert max(e["dbm"] for e in quiet) < core - 15          # far weaker than a link of the square
    walked = [e["dbm"] for e in events if e.get("link") == "h>unoq:ble" and 21 <= e["t"] < 22]
    before = [e["dbm"] for e in events if e.get("link") == "h>unoq:ble" and 10 <= e["t"] < 19]
    assert sum(walked) / len(walked) < sum(before) / len(before) - 3      # the walk dips the level
    assert not [e for e in events if e.get("tx") == "j" and 44.1 <= e["t"] < 54]   # the outage silences j


def test_same_seed_same_hall_readings():
    path = fake.load_path(PATH)
    assert fake.hall_events(path, seed=3) == fake.hall_events(path, seed=3)
    assert fake.hall_events(path, seed=3) != fake.hall_events(path, seed=4)


def test_fake_brain_hall_rows_quiet_then_movement_then_stale():
    path = fake.load_path(PATH)
    all_states = states(path)
    assert all_states[0]["hall"] == []                           # nothing heard yet
    early = at(all_states, 10)
    assert [r["id"] for r in early["hall"]] == hall_ids(path)
    for r in early["hall"]:
        assert set(r) == ROW_KEYS and (r["activity"], r["moving"], r["stale"]) == (0.0, False, False)
        assert r["xy_m"] == path["hall"]["beacons"][r["tx"]] and r["rate_hz"] > 0
    walk = at(all_states, 22)                                    # somebody on h's path, both receivers
    assert [(r["tx"], r["moving"]) for r in walk["hall"]] == [("h", True), ("j", False)] * 2
    assert row(walk, "h>unoq:ble")["activity"] == 1.0
    assert 0.0 < row(at(all_states, 25), "h>unoq:ble")["activity"] < 1.0       # fading out after the walk
    assert row(at(all_states, 27), "h>unoq:ble")["moving"] is False
    assert [(r["tx"], r["moving"]) for r in at(all_states, 34)["hall"]] == [("h", False), ("j", True)] * 2
    gone = at(all_states, 50)                                    # j is silent: stale, and nothing claimed
    for link in ("j>unoq:ble", "j>pi5:ble"):
        assert row(gone, link) == {**row(gone, link), "stale": True, "activity": 0.0, "moving": False, "rate_hz": 0.0}
    assert row(gone, "h>unoq:ble")["stale"] is False
    assert row(at(all_states, 58), "j>unoq:ble")["stale"] is False
    last = at(all_states, 64)                                    # a walk only the board's link sees
    assert row(last, "h>unoq:ble")["moving"] is True and row(last, "h>pi5:ble")["moving"] is False


def test_the_rest_of_the_state_still_passes_the_contract_checker():
    encode = encoder(1763149500000)
    for m in state.run(fake.load_path(PATH)):
        msg = json.loads(encode(m))
        hall = msg.pop("hall", None)
        assert set(errors(msg)) <= UNMEASURED, m["t"]
        if m["type"] == "state":
            assert isinstance(hall, list)
            for r in hall:
                assert 0.0 <= r["activity"] <= 1.0 and r["rate_hz"] >= 0 and isinstance(r["moving"], bool)
                assert not (r["stale"] and (r["moving"] or r["activity"]))
