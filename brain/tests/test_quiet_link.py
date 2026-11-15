"""A link the sensor needs goes quiet with somebody in the area (#650): between its last reading
and SENSOR BLIND the brain never says "nobody is here"."""
from brain.tests.test_core import cmd
from brain.tests.test_layout import desk_feed, taught_desk

WEST = ["west>unoq:ble", "west>pi5:ble", "west>pi5b:ble"]   # every link a person on the left shadows


def watch(brain, msgs):
    """Play messages, taking state at every label as the live loop does. Returns [(recv_t, state, events)]."""
    out = []
    for m in msgs:
        brain.on_message(m)
        if m["type"] == "label":
            out.append((m["recv_t"], brain.state(), brain.pop_events()))
    return out


def test_a_person_whose_links_die_is_never_reported_as_nobody_before_blind():
    brain, ids, play = taught_desk()
    play([(6, 1)], 20)
    assert brain.state()["pred"]["zone"] == 1
    brain.pop_events()
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(8, 1)], start + 66, 21, silent=WEST)     # the beacon is unplugged; they stay
    seen = watch(brain, msgs)
    blind_at = next(t for t, _, events in seen if any(e["kind"] == "blind_on" for e in events))
    assert 3000 <= blind_at - start <= 5000
    before = [state["pred"] for t, state, _ in seen if t <= blind_at]
    assert all(pred is None or pred["present"] for pred in before)       # the old answer, then unknown: never "nobody"
    assert before[0] is not None and before[0]["zone"] == 1              # the first second still stands on real readings
    unknown_at = next(t for t, state, _ in seen if state["pred"] is None)
    assert unknown_at - start <= 2300                                    # unknown well before the 3 to 4 s of blind
    assert not any(e["kind"] == "exit" for _, _, events in seen for e in events)
    assert seen[-1][1]["health"]["status"] == "blind" and seen[-1][1]["pred"] is None


def test_armed_raises_nothing_and_the_still_timer_pauses_while_the_link_is_quiet():
    brain, ids, play = taught_desk()
    brain.on_cmd(cmd("arm", on=True))
    play([(6, 0)], 20)
    brain.pop_events()
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(8, 0)], start + 66, 21, silent=["west>unoq:ble"])
    seen = watch(brain, msgs)
    kinds = [e["kind"] for _, _, events in seen for e in events]
    assert "intrusion" not in kinds and "passed_by" not in kinds and "enter" not in kinds
    assert all(state["alert"]["state"] == "none" for _, state, _ in seen)
    assert all(state["pred"] is None for t, state, _ in seen if t - start > 2300)


def test_somebody_seen_on_the_other_links_still_goes_out_while_one_link_is_quiet():
    brain, ids, play = taught_desk()
    play([(6, 0)], 20)
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(2.5, 2)], start + 66, 21, silent=["west>unoq:ble"])   # a dead link on the far side
    seen = watch(brain, msgs)
    assert seen[-1][1]["health"]["status"] == "degraded"
    assert seen[-1][1]["pred"] is not None and seen[-1][1]["pred"]["zone"] == 2       # a dead link never hides a person


def test_it_comes_back_by_itself_when_the_link_does():
    brain, ids, play = taught_desk()
    play([(6, 0)], 20)
    play([(2.5, 0)], 21, silent=["west>unoq:ble"])
    assert brain.state()["pred"] is None
    play([(3, 0)], 22)
    state = brain.state()
    assert state["health"]["status"] == "ok" and state["pred"] is not None and state["pred"]["present"] is False


def test_an_empty_area_with_every_link_reporting_is_still_nobody_all_the_time():
    brain, ids, play = taught_desk()
    play([(3, 0)], 20)
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(20, 0)], start + 66, 21)
    seen = watch(brain, msgs)
    assert all(state["pred"] is not None and state["pred"]["present"] is False for _, state, _ in seen)


def test_a_link_heard_over_the_hotspot_going_quiet_changes_nothing():
    """Pi B's readings ride the sensing Wi-Fi, which the demo blocks on purpose: not a link the sensor needs."""
    brain, ids, play = taught_desk()
    play([(3, 0)], 20)
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(8, 0)], start + 66, 21, silent=[i for i in ids if ">pi5b:" in i])
    seen = watch(brain, msgs)
    assert all(state["pred"] is not None and state["pred"]["present"] is False for _, state, _ in seen)


def test_a_healthy_link_at_five_readings_a_second_never_blinks_unknown():
    """Measured on the kit: pi5b>unoq:ble gives 4 to 6 readings a second, unevenly. Its chance gaps of
    over a second must not turn "nobody" into unknown."""
    import random

    brain, ids, play = taught_desk()
    slow, rng = "pi5b>unoq:ble", random.Random(5)
    play([(3, 0)], 20)
    brain.expected_hz[slow] = 5.0                  # as a baseline on the kit would have counted it
    brain.health.set_expected({slow: 5.0})
    start = max(brain._last_seen.values())
    msgs, _ = desk_feed(ids, [(300, 0)], start + 66, 22)
    msgs = [m for m in msgs if m.get("link") != slow or rng.random() < 1 / 3]   # 5 a second, at random
    times = [m["recv_t"] for m in msgs if m.get("link") == slow]
    assert max(b - a for a, b in zip(times, times[1:])) > 1000           # the feed does have gaps of over a second
    seen = watch(brain, msgs)
    assert all(state["pred"] is not None and state["pred"]["present"] is False for _, state, _ in seen)
