"""One spot: the Wi-Fi line across the gap decides presence; Bluetooth is a second opinion (#789)."""
import random

import pytest

from brain.presence import Presence

WIFI, BLE = "pi5>pi5b:wifi", "pi5b>unoq:ble"
NODES = {"presence": {"line": WIFI, "second": BLE, "on_db": 7, "off_db": 4, "second_hold_s": 5}}
BASE = {WIFI: -40.0, BLE: -60.0}


def run(p, seconds, wifi=lambda s: 0.0, ble=lambda s: 0.0, wifi_on=lambda s: True, t0=0, seed=0):
    """Wi-Fi 25 times a second (0.3 dB wobble), Bluetooth 5 times (3 dB wobble); one update every 0.1 s.
    wifi(s) / ble(s) are the drops in dB. Returns [(seconds, verdict)]."""
    rng = random.Random(seed)
    out = []
    for i in range(int(seconds * 100)):
        s, t = i / 100, t0 + i * 10
        if i % 4 == 0 and wifi_on(s):
            p.add(WIFI, t, BASE[WIFI] - wifi(s) + rng.uniform(-0.3, 0.3))
        if i % 20 == 0:
            p.add(BLE, t, BASE[BLE] - ble(s) + rng.uniform(-3, 3))
        if i % 10 == 0:
            out.append((s, p.update(t)))
    return out


def new():
    p = Presence(NODES)
    p.set_base(BASE)
    return p


def at(out, s):
    return next(v for t, v in out if t >= s)


def test_a_layout_without_a_presence_block_has_no_opinion_ever():
    for nodes in (None, {}, {"presence": None}, {"zones": []}):
        p = Presence(nodes)
        p.set_base(BASE)
        p.add(WIFI, 0, -80)
        assert not p.active and p.update(100) is None


def test_no_opinion_before_a_baseline():
    p = Presence(NODES)
    p.add(WIFI, 0, -60)
    assert p.update(100) is None


def test_stepping_on_is_found_and_held_while_the_line_stays_down():
    out = run(new(), 40, wifi=lambda s: 17 if 5 <= s < 35 else 0)       # 15 to 21 dB measured; 30 s standing still
    assert at(out, 4) is False
    found = next(s for s, v in out if v)
    assert 5.3 <= found <= 5.8                                           # the 1 s median crosses 7 dB about half way
    assert all(v is True for s, v in out if 6 <= s < 35)                 # never dropped, however still
    gone = next(s for s, v in out if s > 35 and v is False)
    assert 35.3 <= gone <= 35.9


def test_on_at_7_off_at_4_with_a_gap_to_hold_in():
    p = new()
    assert at(run(p, 5, wifi=lambda s: 6), 4) is False                    # 6 dB never raises it
    assert at(run(p, 5, wifi=lambda s: 8, t0=5_000), 4) is True           # 8 dB does
    assert at(run(p, 5, wifi=lambda s: 5, t0=10_000), 4) is True          # back to 5 dB: still held
    assert at(run(p, 5, wifi=lambda s: 3, t0=15_000), 4) is False         # under 4 dB: released


def test_an_empty_minute_with_the_measured_wobble_never_says_present():
    out = run(new(), 60, wifi=lambda s: 0.9 if int(s) % 7 == 0 else 0)   # dips of 0.9 dB, the largest measured
    assert all(v is False for _, v in out)


def test_bluetooth_alone_never_raises_presence():
    out = run(new(), 20, ble=lambda s: 11)                                # the second line falls, the main one doesn't
    assert all(v is False for _, v in out)
    silent = run(new(), 20, ble=lambda s: 11, wifi_on=lambda s: False)    # nor with the main line silent
    assert all(v is None for _, v in silent)


def test_bluetooth_keeps_presence_alive_for_5_s_when_the_wifi_line_goes_silent():
    out = run(new(), 20, wifi=lambda s: 17, ble=lambda s: 9, wifi_on=lambda s: s < 6)
    assert at(out, 5) is True
    assert all(v is True for s, v in out if 7.2 <= s <= 11.8)             # kept alive
    assert all(v is None for s, v in out if s >= 12.5)                    # the hold is over: no opinion


def test_the_hold_ends_at_once_if_bluetooth_is_not_down_either():
    out = run(new(), 12, wifi=lambda s: 17, ble=lambda s: 0, wifi_on=lambda s: s < 6)
    assert at(out, 5) is True and all(v is None for s, v in out if s >= 7.5)


def test_the_wifi_line_coming_back_decides_again():
    out = run(new(), 20, wifi=lambda s: 17 if s < 14 else 0, ble=lambda s: 9, wifi_on=lambda s: not 6 <= s < 9)
    assert at(out, 8) is True and at(out, 12) is True and at(out, 16) is False


def test_the_quiet_level_follows_slow_drift_only_while_nobody_is_there():
    p = new()
    run(p, 300, wifi=lambda s: min(3.0, s / 60))                          # the room drifts 3 dB over 3 minutes
    assert not p.on and 2.0 < BASE[WIFI] - p.quiet[WIFI] < 3.2            # followed, so it never read as a person
    p = new()
    run(p, 300, wifi=lambda s: 17)                                        # somebody stands there for 5 minutes
    assert p.on and p.quiet[WIFI] == BASE[WIFI]                           # the level did not move towards them


def test_a_new_baseline_starts_again_from_nobody():
    p = new()
    run(p, 10, wifi=lambda s: 17)
    assert p.on
    p.set_base({WIFI: -57.0, BLE: -60.0})                                 # baselined with the thing still there
    assert not p.on and p.quiet[WIFI] == -57.0


def test_the_numbers_come_from_the_layout_file_and_must_leave_a_gap():
    p = Presence({"presence": {"line": WIFI, "on_db": 10, "off_db": 2, "second_hold_s": 1}})
    assert (p.on_db, p.off_db, p.second_hold_ms, p.second) == (10.0, 2.0, 1000.0, None)
    d = Presence({"presence": {"line": WIFI}})
    assert (d.on_db, d.off_db, d.second_hold_ms) == (7.0, 4.0, 5000.0)
    with pytest.raises(ValueError):
        Presence({"presence": {"line": WIFI, "on_db": 4, "off_db": 4}})


# ---- through the brain: the line settles the classifier's decision ----

import json
from pathlib import Path

from brain.core import Brain

GATE = json.loads((Path(__file__).parent / "gate3_wifi_nodes.json").read_text())
PERSON = {"present": True, "kind": "person", "zone": 1, "zone_set": [1], "probs": [0.1, 0.9], "motion": "moving",
          "still_s": None, "why": []}
NOBODY = {"present": False, "kind": "none", "zone": 0, "zone_set": [], "probs": [0.9, 0.1], "motion": None,
          "still_s": None, "why": []}
OBJECT = dict(NOBODY, kind="object")


def test_the_layout_file_from_the_radio_lane_names_the_wifi_line():
    assert GATE["presence"]["line"] == WIFI and GATE["presence"]["second"] == BLE
    b = Brain(nodes=GATE)
    assert b.presence.active and (b.presence.on_db, b.presence.off_db) == (7.0, 4.0)
    assert not Brain().presence.active                       # the tests' square has no presence block


def test_no_opinion_leaves_the_classifier_alone():
    b = Brain(nodes=GATE)
    for raw in (PERSON, NOBODY, OBJECT):
        assert b._on_the_line(raw, None) is raw


def test_the_line_says_somebody_when_the_classifier_said_nobody():
    out = Brain(nodes=GATE)._on_the_line(NOBODY, True)
    assert (out["present"], out["kind"], out["zone"], out["zone_set"], out["motion"]) == (True, "person", 1, [1], "still")
    assert NOBODY["present"] is False                        # the classifier's own answer is not changed in place


def test_the_line_says_nobody_when_the_classifier_said_somebody():
    out = Brain(nodes=GATE)._on_the_line(PERSON, False)
    assert (out["present"], out["kind"], out["zone"], out["zone_set"], out["motion"]) == (False, "none", 0, [], None)


def test_something_left_in_the_line_stays_an_object_and_a_person_is_never_one():
    b = Brain(nodes=GATE)
    assert b._on_the_line(OBJECT, True) is OBJECT            # line down, classifier says object: the dead-zone case
    assert b._on_the_line(OBJECT, False) is OBJECT           # line clear: nothing to settle
    assert b._on_the_line(PERSON, True) is PERSON


def test_readings_and_the_baseline_reach_the_rule_through_the_brain():
    b = Brain(nodes=GATE)
    b._set_baseline({k: -40.0 for k in b.links}, {k: 10.0 for k in b.links})
    assert b.presence.quiet[WIFI] == -40.0
    t = 1_000_000
    for i in range(50):                                      # 2 s of the Wi-Fi line 17 dB down
        t += 40
        b.on_message({"v": 2, "type": "rssi", "t": t, "seq": i, "src": "sim", "link": WIFI, "kind": "wifi",
                      "tx": "pi5", "rx": "pi5b", "dbm": -57, "recv_t": t})
    assert b.presence.update(t) is True and b.presence.drop_db == pytest.approx(17.0)
