"""Scripted things other than a person walking: timed objects, router moves,
silent links, a waving hand and the camera going away."""
import math
from statistics import mean, pstdev

import pytest

from sim import fake

WIFI = "pi5>unoq:wifi"


def run(name_or_path, **kw):
    path = fake.load_path(name_or_path) if isinstance(name_or_path, str) else name_or_path
    return list(fake.simulate(path, **kw))


def dbm(events, link, t0=0.0, t1=math.inf):
    return [e["dbm"] for e in events if e["type"] == "rssi" and e["link"] == link and t0 <= e["t"] < t1]


def test_object_only_blocks_while_it_is_there():
    events = run({"duration_s": 30, "objects": [{"x": 1.0, "y": 0.2, "drop_db": 10, "t_on": 10, "t_off": 20}]})
    before, during, after = (mean(dbm(events, WIFI, a, a + 10)) for a in (0, 10, 20))
    assert before - during > 8 and abs(before - after) < 0.5


def test_router_spot_moves_the_pi5_links_only():
    home = run({"duration_s": 5})
    west = run({"duration_s": 5, "router": [{"t": 0, "spot": "S-W30"}]})
    assert mean(dbm(west, "west>pi5:ble")) - mean(dbm(home, "west>pi5:ble")) > 0.5  # closer to west
    assert mean(dbm(west, "east>pi5:ble")) - mean(dbm(home, "east>pi5:ble")) < -0.5
    assert dbm(west, "east>unoq:ble") == dbm(home, "east>unoq:ble")


def test_outage_by_link_and_by_node():
    events = run({"duration_s": 3, "outages": [{"link": WIFI, "t_on": 1, "t_off": 2},
                                               {"node": "west", "t_on": 2}]})
    assert len(dbm(events, WIFI, 1, 2)) == 0 and len(dbm(events, WIFI, 2, 3)) == 15
    assert len(dbm(events, "pi5>unoq:ble", 1, 2)) == 15
    for link in ("west>unoq:ble", "west>pi5:ble"):
        assert len(dbm(events, link, 0, 2)) == 30 and len(dbm(events, link, 2, 3)) == 0


def test_wave_shakes_one_link():
    events = run({"duration_s": 6, "waves": [{"t_on": 2, "t_off": 4.5}]}, noise_db=0.0)
    assert pstdev(dbm(events, WIFI, 2, 4.5)) > 2 and pstdev(dbm(events, WIFI, 0, 2)) == 0
    assert pstdev(dbm(events, "pi5>unoq:ble")) == 0


def test_camera_states_stop_labels_and_report_at_once():
    events = run({"duration_s": 4, "camera": [{"t": 1.4, "state": "stalled"}, {"t": 2.6, "state": "off"}]})
    labels = [e["t"] for e in events if e["type"] == "label"]
    assert max(labels) < 1.4
    cams = [(e["t"], e["state"], e["fps"] > 0) for e in events if e["type"] == "cam"]
    assert cams == [(0.0, "on", True), (1.0, "on", True), (1.4, "stalled", False), (2.0, "stalled", False),
                    (2.6, "off", False), (3.0, "off", False)]


# ---- the path files ----

def crossings(values, band=1.5):
    """Alternating crossings of +/-band around the median."""
    mid, side, n = sorted(values)[len(values) // 2], 0, 0
    for v in values:
        now = 1 if v - mid > band else -1 if v - mid < -band else 0
        if now and now != side:
            side, n = now, n + 1
    return n


def test_wave_checkin_meets_the_contract_rule():
    events = run("wave_checkin", noise_db=0.3)
    assert crossings(dbm(events, WIFI, 14, 16.5)) >= 4
    labels = [e for e in events if e["type"] == "label" and 2 <= e["t"] < 22]
    assert {(e["zone"], e["motion"]) for e in labels} == {(4, "still")}  # still well past the 10 s limit
    for link in ("east>pi5:ble", "pi5>unoq:ble"):  # nothing else moves during the wave
        assert abs(mean(dbm(events, link, 14, 16.5)) - mean(dbm(events, link, 10, 14))) < 1


def test_tray_t1_blocks_the_router_link_after_a_clean_baseline():
    events = run("tray_t1")
    tray = fake.load_path("tray_t1")["objects"][0]
    assert (tray["x"], tray["y"], tray["t_on"] >= 20) == (1.0, 0.2, True)  # contract T1, after a 20 s baseline
    assert mean(dbm(events, WIFI, 0, 25)) - mean(dbm(events, WIFI, 25, 55)) > 8
    assert pstdev(dbm(events, WIFI, 25, 55)) < 1.5
    assert not any(e["persons_in_frame"] for e in events if e["type"] == "label")


def test_router_move_clears_the_link():
    events = run("router_move")
    clean, blocked, moved = (mean(dbm(events, WIFI, a, b)) for a, b in ((0, 25), (25, 45), (45, 60)))
    assert clean - blocked > 8 and moved - blocked > 5
    assert abs(mean(dbm(events, WIFI, 65, 75)) - clean) < 0.5  # home again, tray gone


def test_dropped_link_goes_silent_for_ten_seconds():
    events = run("dropped_link")
    for link in ("east>unoq:ble", "east>pi5:ble"):
        assert len(dbm(events, link, 10, 20)) == 0 and len(dbm(events, link, 20, 30)) == 150
    assert len(dbm(events, "west>unoq:ble", 10, 20)) == 150


def test_camera_unplug_keeps_the_radio_going():
    events = run("camera_unplug")
    assert max(e["t"] for e in events if e["type"] == "label") < 14
    assert {e["state"] for e in events if e["type"] == "cam" and e["t"] >= 14} == {"off"}
    assert len(dbm(events, WIFI, 14, 32)) == 18 * 15
