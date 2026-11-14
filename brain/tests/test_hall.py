"""Hall links (brain/hall.py): the activity rule on made-up long links, and proof that the core
links' state is the same with and without hall beacons.

The readings here are synthetic: a weak link heard a few times a second at uneven moments, on three
channels that sit at different levels. They test the rule's logic, not how a real hall behaves.
"""
import copy
import json
import logging
import random

import pytest

from brain import hall as H
from brain.core import NODES_JSON, Brain
from brain.tests.simdata import T0_MS, sim_to_v2

HALL = {"beacons": [{"node": "h", "id": "H", "data_hex": "FFFF525348", "xyz_m": [14.0, 9.5, 1.2]},
                    {"node": "j", "id": "J", "data_hex": "FFFF52534A", "xyz_m": None}]}
LINKS = ["h>unoq:ble", "j>unoq:ble", "h>pi5:ble", "j>pi5:ble"]     # receivers in nodes.json order, then beacons
ROW_KEYS = {"id", "tx", "rx", "xy_m", "activity", "moving", "rate_hz", "stale"}


def nodes_doc(with_hall=True):
    doc = json.loads(NODES_JSON.read_text(encoding="utf-8"))
    doc.pop("hall", None)
    if with_hall:
        doc["hall"] = copy.deepcopy(HALL)
    return doc


def rssi(link, t, dbm):
    tx, rest = link.split(">")
    return {"v": 2, "type": "rssi", "t": t, "recv_t": t, "seq": 0, "src": "live", "link": link,
            "kind": "ble", "tx": tx, "rx": rest.split(":")[0], "dbm": dbm}


def far_link(seconds, seed=0, sent_hz=25.0, heard=0.3, level=-82.0, walks=(), t0=T0_MS):
    """(t ms, dbm) for a weak link: `heard` of the adverts arrive, each on one of three channels
    that sit at different levels, with 0.7 dB of noise. walks: (start s, end s) spans in which a
    body crosses the path and the level dips by up to 7 dB and flutters."""
    rng = random.Random(seed)
    channel = (-1.5, 0.0, 1.0)
    out, t = [], 0.0
    while t < seconds:
        t += 1.0 / sent_hz + rng.uniform(0.0, 0.010)
        if rng.random() >= heard:
            continue
        dbm = level + rng.choice(channel) + rng.gauss(0.0, 0.7)
        for start, end in walks:
            if start <= t < end:
                mid, half = (start + end) / 2, (end - start) / 2
                dbm -= 7.0 * max(0.0, 1.0 - abs(t - mid) / half) * max(0.0, 1.0 + rng.gauss(0.0, 0.3))
        out.append((t0 + round(t * 1000), round(dbm)))
    return out


def play(hall, link, readings, seconds, t0=T0_MS):
    """Feed the readings and ask for rows every 0.1 s, like the live loop. Returns [(s, row)]."""
    rows, i = [], 0
    for tick in range(int(seconds * 10) + 1):
        now = t0 + tick * 100
        while i < len(readings) and readings[i][0] <= now:
            assert hall.take(rssi(link, *readings[i]))
            i += 1
        row = next(r for r in hall.rows(now) if r["id"] == link) if i else None
        if row:
            rows.append((tick / 10, row))
    return rows


def test_spread_is_the_std_of_half_second_means_and_needs_four_bins():
    now = 10_000
    assert H.spread_db([(now - 100, -80), (now - 600, -80), (now - 1100, -80)], now) is None
    steady = [(now - 100 - 500 * k, -80) for k in range(6)]
    assert H.spread_db(steady, now) == 0.0
    # a burst inside one bin counts once: its mean, not its many readings
    burst = steady + [(now - 120, -80)] * 20
    assert H.spread_db(burst, now) == 0.0
    stepped = [(now - 100 - 500 * k, -80 if k < 3 else -86) for k in range(6)]
    assert H.spread_db(stepped, now) == pytest.approx(3.0)
    assert H.spread_db([(now - 5000, -60)] + steady, now) == 0.0     # older than 3 s: ignored


def test_quiet_level_needs_twenty_samples_and_has_a_floor():
    assert H.quiet_db([(i, 1.0) for i in range(19)]) is None
    assert H.quiet_db([(i, 0.1) for i in range(20)]) == H.QUIET_FLOOR_DB
    mostly_busy = [(i, 5.0) for i in range(70)] + [(i, 1.2) for i in range(30)]
    assert H.quiet_db(mostly_busy) == 1.2     # the quiet moments set it, even when they are the minority


def test_no_hall_section_takes_nothing_and_adds_nothing():
    hall = H.Hall.from_nodes(nodes_doc(with_hall=False))
    assert hall.take(rssi("h>unoq:ble", T0_MS, -80)) is False
    assert hall.rows(T0_MS) == [] and hall.add_to({"x": 1}, T0_MS) == {"x": 1}


def test_only_hall_links_are_taken():
    hall = H.Hall.from_nodes(nodes_doc())
    assert hall.take(rssi("east>unoq:ble", T0_MS, -60)) is False
    assert hall.take({"v": 2, "type": "label", "recv_t": T0_MS, "link": "h>unoq:ble"}) is False
    assert hall.take(rssi("h>unoq:ble", T0_MS, -80)) is True
    assert hall.add_to({}, T0_MS) == {"hall": [
        {"id": "h>unoq:ble", "tx": "h", "rx": "unoq", "xy_m": [14.0, 9.5], "activity": 0.0,
         "moving": False, "rate_hz": 0.5, "stale": True}]}


def test_hall_links_are_every_hall_beacon_heard_by_every_receiver_in_nodes_json():
    doc = nodes_doc()
    doc["nodes"].append({"id": "pi5b", "side": "X", "xyz_m": [3.0, 1.0, 1.0], "roles": ["beacon", "receiver"]})
    hall = H.Hall.from_nodes(doc)
    for link in ("j>pi5b:ble", "h>pi5b:ble", "h>unoq:ble"):
        assert hall.take(rssi(link, T0_MS, -85)) is True
    assert [r["id"] for r in hall.rows(T0_MS)] == ["h>unoq:ble", "h>pi5b:ble", "j>pi5b:ble"]
    assert [(r["tx"], r["rx"]) for r in hall.rows(T0_MS)] == [("h", "unoq"), ("h", "pi5b"), ("j", "pi5b")]
    # heard by something that is no receiver in nodes.json: still a hall reading (the core never
    # sees it), but there is no row for it
    assert hall.take(rssi("h>east:ble", T0_MS, -85)) is True and len(hall.rows(T0_MS)) == 3
    # a core link is never taken, whoever hears it
    assert hall.take(rssi("pi5b>unoq:ble", T0_MS, -60)) is False
    assert hall.take(rssi("east>pi5b:ble", T0_MS, -60)) is False


def test_a_hall_beacon_named_like_a_node_of_the_square_turns_the_hall_off(caplog):
    doc = nodes_doc()
    doc["hall"]["beacons"][0]["node"] = "east"
    hall = H.Hall.from_nodes(doc)
    assert hall.take(rssi("east>unoq:ble", T0_MS, -60)) is False and hall.rows(T0_MS) == []


def test_rows_come_in_nodes_order_once_heard_and_carry_the_beacon_position():
    hall = H.Hall.from_nodes(nodes_doc())
    for link in ("j>pi5:ble", "h>pi5:ble"):
        hall.take(rssi(link, T0_MS, -85))
    rows = hall.rows(T0_MS + 100)
    assert [r["id"] for r in rows] == ["h>pi5:ble", "j>pi5:ble"]
    assert all(set(r) == ROW_KEYS for r in rows)
    assert rows[0]["xy_m"] == [14.0, 9.5] and rows[1]["xy_m"] is None     # j has not been measured


def test_a_quiet_link_never_reads_as_moving():
    hall = H.Hall.from_nodes(nodes_doc())
    rows = play(hall, "h>unoq:ble", far_link(600, seed=1), 600)
    assert not any(r["moving"] for _, r in rows)
    settled = [r for s, r in rows if s > 30]
    assert not any(r["stale"] for r in settled)
    assert max(r["activity"] for r in settled) < H.ON
    assert 4 < settled[-1]["rate_hz"] < 12     # about 30% of 22 adverts a second


@pytest.mark.parametrize("seed", range(5))
def test_a_body_crossing_the_path_turns_moving_on_and_then_off(seed):
    hall = H.Hall.from_nodes(nodes_doc())
    walks = [(60.0, 62.0), (120.0, 122.0)]
    rows = play(hall, "h>unoq:ble", far_link(180, seed=seed, walks=walks), 180)
    for start, end in walks:
        during = [r for s, r in rows if start + 0.5 <= s <= end + 2.0]
        assert any(r["moving"] for r in during), "the crossing was missed"
        assert max(r["activity"] for r in during) >= H.ON
        after = [r for s, r in rows if end + 6.0 <= s <= end + 30.0]
        assert not any(r["moving"] for r in after), "moving stayed on after the path cleared"
    assert not any(r["moving"] for s, r in rows if s < 59.0)


def test_moving_has_hysteresis(monkeypatch):
    """On at 0.5; between 0.25 and 0.5 it holds; off only after 1 s under 0.25."""
    link = H._Link("h>unoq:ble", "h", "unoq", None)
    level = {"spread": 1.0}
    monkeypatch.setattr(H, "spread_db", lambda readings, now: level["spread"])
    monkeypatch.setattr(H, "quiet_db", lambda samples: 1.0)
    now = T0_MS
    link.row(now)

    def step(spread, ms=100):
        nonlocal now
        level["spread"], now = spread, now + ms
        return link.row(now)

    for _ in range(31):
        row = step(1.0)
    assert row == {**row, "stale": False, "moving": False, "activity": 0.0}
    assert step(2.0)["activity"] == 0.0                    # twice the quiet level: still nothing
    assert step(3.9)["moving"] is False                    # activity 0.48
    assert step(4.0) == {**row, "activity": 0.5, "moving": True}
    assert step(9.0)["activity"] == 1.0
    assert all(step(3.2)["moving"] for _ in range(30))     # 0.3: holds for as long as it likes
    assert all(step(2.5)["moving"] for _ in range(10))     # 0.12 for 1.0 s: on until the full second
    assert step(2.5)["moving"] is False
    assert step(3.5)["moving"] is False                    # 0.38 does not turn it back on


def test_stale_when_the_readings_stop_and_clear_three_seconds_after_they_return():
    hall = H.Hall.from_nodes(nodes_doc())
    readings = [r for r in far_link(120, seed=3) if not 60_000 <= r[0] - T0_MS < 80_000]
    rows = play(hall, "h>unoq:ble", readings, 120)
    by_s = dict(rows)
    assert by_s[59.0]["stale"] is False
    assert by_s[62.0] == {**by_s[62.0], "stale": True, "activity": 0.0, "moving": False}
    assert by_s[79.0]["stale"] is True and by_s[79.0]["rate_hz"] == 0.0
    assert by_s[82.0]["stale"] is True          # readings are back, but not for 3 s yet
    assert by_s[86.0]["stale"] is False


def test_a_link_heard_about_once_a_second_is_stale_not_quiet():
    hall = H.Hall.from_nodes(nodes_doc())
    readings = [(T0_MS + 1100 * k, -88) for k in range(1, 60)]
    rows = play(hall, "j>pi5:ble", readings, 60)
    assert all(r["stale"] and not r["moving"] and r["activity"] == 0.0 for _, r in rows)


def test_bad_input_and_a_bug_inside_never_raise(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="brain.hall")
    assert H.Hall.from_nodes({"hall": {"beacons": "nonsense"}}).rows(T0_MS) == []
    assert H.Hall.from_nodes(None).take({"type": "rssi"}) is False
    hall = H.Hall.from_nodes(nodes_doc())
    assert hall.take({"type": "rssi", "link": ["not", "hashable"]}) is False
    assert hall.take("not a message") is False
    assert hall.take({"type": "rssi", "link": "h>unoq:ble", "recv_t": T0_MS, "dbm": None}) is True   # ours, dropped
    assert hall.rows(T0_MS) == []
    hall.take(rssi("h>unoq:ble", T0_MS, -80))
    monkeypatch.setattr(H._Link, "row", lambda self, now: 1 / 0)
    assert hall.rows(T0_MS) == [] and hall.rows(T0_MS + 100) == []
    assert hall.add_to({"x": 1}, T0_MS) == {"x": 1}
    said = [r for r in caplog.records if r.getMessage().startswith("hall links")]
    assert len(said) == 1     # said once, not ten times a second


def test_a_bug_in_the_hall_code_does_not_stop_the_brain(monkeypatch):
    brain = Brain(nodes=nodes_doc())
    brain.on_message(rssi("h>unoq:ble", T0_MS, -80))
    monkeypatch.setattr(H._Link, "row", lambda self, now: 1 / 0)
    monkeypatch.setattr(H._Link, "add", lambda self, t, dbm: 1 / 0)
    brain.on_message(rssi("h>unoq:ble", T0_MS + 50, -80))
    brain.on_message(rssi("east>unoq:ble", T0_MS + 60, -60))
    state = brain.state()
    assert "hall" not in state and [row["id"] for row in state["links"]] == ["east>unoq:ble"]


def cmd(name, **args):
    return {"v": 2, "type": "cmd", "cmd": name, "args": args}


def run_demo(brain, hall_readings=()):
    """Baseline, a recorded walk, training, then the whole demo path. Returns every state and event
    as JSON text, one every 0.1 s. hall_readings are slipped in between the core links' messages."""
    extra = sorted(hall_readings, key=lambda m: m["recv_t"])
    out, t0, i = [], T0_MS, 0

    def feed(path, seed, meta=None):
        nonlocal t0, i
        last = 0
        for m in sim_to_v2(path, seed=seed, meta=meta, t0=t0):
            while i < len(extra) and extra[i]["recv_t"] <= m["recv_t"]:
                brain.on_message(dict(extra[i]))
                i += 1
            brain.on_message(m)
            if m["recv_t"] - last >= 100:
                last = m["recv_t"]
                state = brain.state()
                state["model"]["train_s"] = None     # wall time, like ms_per_decision
                out.extend(json.dumps(x, sort_keys=True) for x in [*brain.pop_events(), state])
        t0 = m["recv_t"] + 100

    brain.on_cmd(cmd("baseline"))
    feed("empty_room", 1)
    for session, path, seed in (("s01", "empty_room", 2), ("s02", "zone_tour", 3)):
        brain.on_cmd(cmd("record_start", session=session, purpose="train", walker="w1"))
        feed(path, seed, meta={"session": session, "purpose": "train", "walker": "w1"})
        brain.on_cmd(cmd("record_stop"))
    brain.on_cmd(cmd("train"))
    feed("demo", 4)
    return out, t0


def test_the_core_links_state_is_the_same_with_and_without_hall_beacons(monkeypatch):
    monkeypatch.setattr("brain.core.time.perf_counter", lambda: 0.0)   # ms_per_decision is wall time
    plain, end = run_demo(Brain(nodes=nodes_doc(with_hall=False)))
    listed, _ = run_demo(Brain(nodes=nodes_doc()))                    # configured, never heard
    assert listed == plain                                           # byte for byte, no "hall" key at all
    assert '"hall"' not in "".join(plain)

    seconds = (end - T0_MS) / 1000
    readings = [rssi(link, t, dbm) for n, link in enumerate(LINKS)
                for t, dbm in far_link(seconds, seed=n, walks=[(40.0, 42.0), (90.0, 92.0)])]
    brain = Brain(nodes=nodes_doc())
    heard, _ = run_demo(brain, readings)
    assert len(heard) == len(plain)
    seen_moving = False
    for with_hall, without in zip(heard, plain):
        msg = json.loads(with_hall)
        rows = msg.pop("hall", None)
        assert json.dumps(msg, sort_keys=True) == without
        seen_moving = seen_moving or any(r["moving"] for r in rows or [])
    assert seen_moving and json.loads(plain[-1])["model"]["trained"]
    assert all(m["link"] in brain.links for s in brain.sessions.values() for m in s["messages"] or []
               if m["type"] == "rssi")     # the recordings held for training carry no hall readings
