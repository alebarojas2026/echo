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
        assert {b["still_s"] for _, b in blocks} == {0}          # nothing counts toward a limit here


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


# ---- smoothing before the still timer (#220) ----

STILL = {"present": True, "zone": 4, "zone_set": [4], "kind": "person", "motion": "still"}


def stand(blips, seconds=12):
    """A still stand in zone 4 at 10 decisions a second; blips maps a decision index to another pred.
    Returns (watch, seconds at which the alert came on, or None)."""
    watch = Watch(LIMITS, Led())
    on_at = None
    for i in range(seconds * 10 + 1):
        watch.on_pred(T0 + i * 100, blips.get(i, STILL))
        if on_at is None and watch.alerting:
            on_at = i / 10
    return watch, on_at


def test_one_moving_blip_does_not_restart_the_still_timer():
    _, on_at = stand({50: dict(STILL, motion="moving")})
    assert on_at == 10.0


def test_one_flipped_zone_or_dropped_person_does_not_restart_it():
    gone = {"present": False, "zone": 0, "zone_set": [], "kind": "none", "motion": None}
    watch, on_at = stand({40: dict(STILL, zone=3, zone_set=[3]), 70: gone,
                          85: dict(STILL, kind="object")})
    assert on_at == 10.0 and watch.alert_zone == 4
    assert ("show_zone", 3) in watch.led.calls and ("show_zone", 0) in watch.led.calls   # the grid shows each decision


def test_a_second_of_real_walking_resets_the_timer():
    walking = {i: dict(STILL, motion="moving") for i in range(50, 60)}
    watch, on_at = stand(walking, seconds=14)
    assert on_at is None                           # 5 s + 8 s apart never reach 10 s
    watch, on_at = stand(walking, seconds=17)
    assert 15.5 <= on_at <= 16.0                   # 10 s after the walking ended


def test_a_real_zone_change_resets_the_timer_and_counts_in_the_new_zone():
    moved = {i: dict(STILL, zone=1, zone_set=[1]) for i in range(60, 200)}
    watch, on_at = stand(moved, seconds=15)
    assert on_at is None and watch.zone == 1       # zone 1's limit is 60 s
    assert 8 < watch.alert_block()["still_s"] < 9.5 and watch.alert_block()["limit_s"] == 60


def test_walking_out_clears_the_count():
    gone = {"present": False, "zone": 0, "zone_set": [], "kind": "none", "motion": None}
    watch, on_at = stand({i: gone for i in range(50, 200)}, seconds=15)
    assert on_at is None and watch.still_ms == 0 and watch.alert_block()["state"] == "none"


def mixed(counts, seconds=4):
    """4 s still in zone 4, then 10 decisions mixed as given ((pred, how many) pairs, interleaved)."""
    watch = Watch(LIMITS, Led())
    i = 0
    for i in range(seconds * 10):
        watch.on_pred(T0 + i * 100, STILL)
    before = watch.still_ms
    rest = [p for p, n in counts for _ in range(n)]
    order = sorted(range(len(rest)), key=lambda k: (k % 3, k))    # shuffle them a little
    for j, k in enumerate(order):
        watch.on_pred(T0 + (i + 1 + j) * 100, rest[k])
    return watch, before


def test_no_zone_takes_over_without_6_of_the_last_10():
    gone = {"present": False, "zone": 0, "zone_set": [], "kind": "none", "motion": None}
    watch, before = mixed([(STILL, 3), (dict(STILL, zone=3, zone_set=[3]), 4), (gone, 3)])
    assert watch.zone == 4 and watch.still_ms > before      # 4 of 10 is the most common, not a majority


def test_no_kind_takes_over_without_6_of_the_last_10():
    thing = dict(STILL, kind="object")
    nothing = dict(STILL, kind="none")
    watch, before = mixed([(STILL, 4), (thing, 3), (nothing, 3)])
    assert watch._kind == "person" and watch.still_ms > before   # object and none are different kinds
    watch, before = mixed([(STILL, 2), (thing, 2), (nothing, 6)])
    assert watch._kind == "none" and watch.still_ms == 0         # 6 of 10 does take over


def test_a_single_flipped_zone_still_cancels_a_wave_in_progress():
    watch = Watch(LIMITS, Led())
    watch.on_pred(T0, STILL)
    marks = []
    watch.checkin_rule.zone_changed = marks.append
    watch.on_pred(T0 + 100, dict(STILL, zone=3, zone_set=[3]))   # one flipped decision
    watch.on_pred(T0 + 200, STILL)
    assert marks == [T0 + 100, T0 + 200] and watch.zone == 4     # raw changes reach the check-in rule


def noisy_link(rate_hz, seconds, sigma_db=1.5, wave_db=0.0, seed=0):
    """Check-ins on a link with random noise (and, with wave_db, a 2 Hz swing for 2.5 s in every 20 s)."""
    import math
    import random
    rng, rule, fired = random.Random(seed), CheckIn(), 0
    for i in range(int(seconds * rate_hz)):
        t = int(i * 1000 / rate_hz)
        dbm = -50 + rng.gauss(0, sigma_db)
        if wave_db and 10 <= (t / 1000) % 20 < 12.5:
            dbm += wave_db * math.sin(2 * math.pi * 2.0 * t / 1000)
        fired += rule.push(T0 + t, CHECKIN_LINK, round(dbm))
    return fired


def test_a_faster_reader_does_not_get_more_check_ins_out_of_the_same_noise():
    """The Wi-Fi reader sends about 50 readings a second, not 10. The same noisy link must not
    cross the +/-1.5 dB lines more often just because it is read more often."""
    slow = sum(noisy_link(10, 600, seed=s) for s in range(3))
    fast = sum(noisy_link(50, 600, seed=s) for s in range(3))
    assert fast <= slow, f"{fast} check-ins from noise at 50 readings a second, {slow} at 10"


def test_a_wave_still_checks_in_at_every_reading_rate():
    for rate in (10, 15, 20, 50):
        assert noisy_link(rate, 200, sigma_db=1.0, wave_db=4.0) >= 8, rate   # 10 waves in 200 s
