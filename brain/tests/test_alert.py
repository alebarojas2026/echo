import json

import pytest

from brain.alert import CHECKIN_LINK, CheckIn, Watch, zone_limits
from sim import fake, wire

T0 = 1_763_149_500_000
LIMITS = {1: 60, 2: None, 3: None, 4: 10}


class Led:
    def __init__(self):
        self.calls = []

    def show_zone(self, n): self.calls.append(("show_zone", n))
    def alert(self, on): self.calls.append(("alert", on))
    def smile(self): self.calls.append(("smile",))


def run(path_name, seed=0, watch=None, **overrides):
    """Play a sim path into a Watch, using the camera's labels as the decisions.

    Returns (watch, events as (seconds, kind, info), alert blocks as (seconds, block)).
    """
    watch = watch or Watch(LIMITS, Led())
    path = {**fake.load_path(path_name), **overrides}
    encode = wire.encoder(T0)
    events, blocks = [], []
    for ev in fake.simulate(path, seed=seed):
        msg = json.loads(encode(ev))
        t = msg["recv_t"] = msg["t"]
        if msg["type"] == "rssi":
            watch.on_rssi(msg)
        elif msg["type"] == "label":
            watch.on_pred(t, {"present": msg["present"], "zone": msg["zone"] or None,
                              "kind": "person" if msg["present"] else "none", "motion": msg["motion"]})
            blocks.append(((t - T0) / 1000, watch.alert_block()))
        events += [((t - T0) / 1000, kind, info) for kind, info in watch.pop_events()]
    return watch, events, blocks


def test_limits_come_from_nodes_json():
    assert zone_limits() == LIMITS


def test_wave_path_alerts_then_checks_in():
    watch, events, blocks = run("wave_checkin")
    assert [k for _, k, _ in events] == ["alert_on", "checkin", "alert_off"]
    (t_on, _, on), (t_in, _, checkin), (t_off, _, off) = events
    assert 10.5 < t_on < 12.5 and on == {"zone": 4}            # still from about 1 s, limit 10 s
    assert 14 < t_in <= 16.6 and checkin == {"zone": 4, "link": CHECKIN_LINK}   # the wave is 14-16.5 s
    assert t_off == t_in and off == {"zone": 4}
    assert watch.checkin == {"t": T0 + round(t_in * 1000), "link": CHECKIN_LINK}
    def at(seconds):
        return next(b for s, b in blocks if s >= seconds)

    assert at(5)["state"] == "counting" and at(13)["state"] == "check_on" and at(18)["state"] == "counting"
    assert at(13)["zone"] == 4 and at(13)["limit_s"] == 10 and at(13)["still_s"] >= 10
    assert at(18)["still_s"] < 4                                # the timer started again
    assert watch.led.calls == [("show_zone", 4), ("alert", True), ("smile",), ("alert", False),
                               ("show_zone", 0)]


def test_standing_still_without_a_wave_stays_alerting():
    for seed in range(5):
        watch, events, blocks = run("wave_checkin", seed=seed, waves=[])
        assert [k for _, k, _ in events] == ["alert_on"], seed   # noise never looks like a wave
        assert blocks[-1][1]["state"] == "check_on"              # latched after they walk out
        assert watch.checkin is None


def test_zone_without_a_limit_never_alerts():
    for seed in range(3):
        hall = [{"t": 0, "x": 0.0, "y": 0.5}, {"t": 1, "x": 0.5, "y": 0.5}, {"t": 20, "x": 0.5, "y": 0.5},
                {"t": 21, "x": 0.0, "y": 0.5}, {"t": 21.1, "x": None}]
        watch, events, blocks = run("stand_still", seed=seed, person=hall)   # zone 3: limit null
        assert events == [] and {b["state"] for _, b in blocks} == {"none"}
        assert max(b["still_s"] for _, b in blocks) > 10         # still_s counts all the same


def test_empty_room_and_walking_do_nothing():
    for name in ("empty_room", "zone_tour"):
        watch, events, _ = run(name, seed=3)
        assert events == [], name


def test_reset_alert_clears_and_restarts_the_timer():
    watch = Watch(LIMITS, Led())
    pred = {"present": True, "zone": 4, "kind": "person", "motion": "still"}
    for t in range(0, 12_000, 100):
        watch.on_pred(T0 + t, pred)
    assert watch.alert_block()["state"] == "check_on"
    watch.reset_alert()
    assert watch.pop_events() == [("alert_on", {"zone": 4}), ("alert_off", {"zone": 4})]
    assert watch.alert_block() == {"state": "none", "zone": None, "still_s": 0.0, "limit_s": None}
    watch.on_pred(T0 + 12_100, pred)
    assert watch.alert_block()["state"] == "counting"


def test_timer_pauses_while_pred_is_null_and_objects_never_alert():
    watch = Watch(LIMITS)
    pred = {"present": True, "zone": 4, "kind": "person", "motion": "still"}
    for t in range(0, 6_000, 100):
        watch.on_pred(T0 + t, pred)
    for t in range(6_000, 30_000, 100):
        watch.on_pred(T0 + t, None)                 # sensor blind for 24 s
    watch.on_pred(T0 + 30_000, pred)
    assert watch.alert_block()["state"] == "counting" and watch.alert_block()["still_s"] < 7
    thing = Watch(LIMITS)
    for t in range(0, 30_000, 100):
        thing.on_pred(T0 + t, {"present": False, "zone": None, "kind": "object", "motion": None})
    assert thing.alert_block()["state"] == "none" and thing.pop_events() == []


def wave(rule, t0, n=40, amp=4.0, other=None):
    """Feed a 2 Hz wave at 15 readings a second; returns the times it fired."""
    import math
    fired = []
    for i in range(n):
        t = t0 + i * 67
        if other:
            rule.push(t, "east>unoq:ble", other(i))
        if rule.push(t, CHECKIN_LINK, -46 + amp * math.sin(2 * math.pi * 2 * i / 15)):
            fired.append(t)
    return fired


def test_check_in_needs_a_big_enough_wave():
    assert wave(CheckIn(), T0)
    assert not wave(CheckIn(), T0, amp=1.0)


def test_check_in_is_blocked_by_a_zone_change_or_another_link_moving():
    rule = CheckIn()
    rule.zone_changed(T0 + 2_600)                      # the zone changed after the wave began
    assert not wave(rule, T0, n=38)
    assert not wave(CheckIn(), T0, other=lambda i: -58 - (8 if i > 10 else 0))   # someone walked by
    assert wave(CheckIn(), T0, other=lambda i: -58 + (i % 2))                    # ordinary noise is fine


def test_led_shows_a_question_mark_for_null_pred_and_for_two_zones():
    watch = Watch(LIMITS, Led())
    one = {"present": True, "zone": 2, "zone_set": [2], "kind": "person", "motion": "moving"}
    two = dict(one, zone_set=[2, 4])
    steps = [one, one, None, None, one, two, two, one,
             {"present": False, "zone": None, "zone_set": [], "kind": "none", "motion": None}, None]
    for i, pred in enumerate(steps):
        watch.on_pred(T0 + i * 100, pred)
    # 2, "?" while blind, 2 again, "?" for two zones, 2 again, the empty dot, "?" again
    assert watch.led.calls == [("show_zone", n) for n in (2, -1, 2, -1, 2, 0, -1)]


def test_led_starts_with_a_question_mark_when_pred_is_null():
    watch = Watch(LIMITS, Led())
    watch.on_pred(T0, None)
    watch.on_pred(T0 + 100, None)
    assert watch.led.calls == [("show_zone", -1)]


def test_reset_also_forgets_the_check_in_but_reset_alert_keeps_it():
    watch, _, _ = run("wave_checkin")
    assert watch.checkin is not None
    watch.reset_alert()
    assert watch.checkin is not None
    watch.reset()
    assert watch.checkin is None and watch.alert_block()["state"] == "none"
