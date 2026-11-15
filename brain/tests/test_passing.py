"""A walk straight through the presence line (brain/passing.py): the rule alone on hand-made
readings, and the whole brain on the gate layout with the made-up feed (brain/tests/gatefeed.py).

The feed is a stand-in: it shows the rule holds on dips shaped like the kit's (about 15 dB for
a third of a second). It is not a measurement of the real desk.
"""
import json
from pathlib import Path

from brain.core import Brain
from brain.passing import HOLD_OFF_MS, SETTLE_MS, PassThrough
from brain.tests.test_core import cmd
from brain.tests.test_gate import Kit, cold_kit
from contracts import check

BASE = -44.0
STEP = 40          # 25 readings a second
WANTED = ("enter", "exit", "passed_by", "intrusion", "checkin", "alert_on")


class Line:
    """Readings of the line into the rule, one every 40 ms, with nobody announced unless busy says so."""

    def __init__(self, **numbers):
        self.rule, self.t = PassThrough(**numbers), 0
        self.empty(HOLD_OFF_MS / 1000 + 0.5)

    def feed(self, seconds, down, busy=False, base=BASE, skip=()):
        for i in range(round(seconds * 1000 / STEP)):
            self.t += STEP
            if i not in skip:
                self.rule.on_reading(self.t, base - down if base is not None else BASE - down, base, busy)
        return self

    def empty(self, seconds, **kw):
        return self.feed(seconds, 0.0, **kw)


def test_a_short_deep_dip_is_one_walk_through_once_the_presence_window_has_passed():
    line = Line().feed(0.4, 15)
    line.empty((SETTLE_MS - 100) / 1000)
    assert line.rule.pop() == 0                      # not yet: the 1 s window could still say somebody is here
    assert line.empty(0.3).rule.pop() == 1
    assert line.empty(10).rule.pop() == 0            # and once only


def test_the_kits_shortest_and_longest_crossings_count_and_its_empty_line_does_not():
    for seconds, down in ((0.28, 14), (0.44, 15), (0.52, 14), (0.84, 15), (0.49, 16)):
        assert Line().feed(seconds, down).empty(2).rule.pop() == 1, seconds
    line = Line()
    for i in range(1500):                            # a minute of the empty line: it dips 2 dB at most
        line.feed(STEP / 1000, 2.0 if i % 7 == 0 else 0.5)
    assert line.rule.pop() == 0


def test_a_dip_that_is_too_brief_too_shallow_or_too_long_is_not_one():
    assert Line().feed(0.12, 15).empty(2).rule.pop() == 0     # three readings: under pass_min_s
    assert Line().feed(0.6, 8).empty(2).rule.pop() == 0       # never pass_db down
    assert Line().feed(1.6, 15).empty(2).rule.pop() == 0      # over pass_max_s: somebody stopped
    assert Line().feed(0.6, 15).feed(3, 5).empty(2).rule.pop() == 0   # did not come back within clear_db in time
    assert Line(pass_db=20).feed(0.4, 15).empty(2).rule.pop() == 0
    assert Line(min_s=0.5).feed(0.4, 15).empty(2).rule.pop() == 0
    assert Line(max_s=0.3).feed(0.4, 15).empty(2).rule.pop() == 0


def test_one_missing_reading_is_let_through_and_a_silent_line_is_not():
    assert Line().feed(0.24, 15, skip=(2,)).empty(2).rule.pop() == 1          # five of six readings arrived
    assert Line().feed(0.2, 15).feed(0.04, 6).feed(0.12, 15).empty(2).rule.pop() == 1   # one shallower reading in the run
    assert Line().feed(0.12, 15).feed(0.08, 6).feed(0.12, 15).empty(2).rule.pop() == 0  # two: no run of pass_min_s
    assert Line().feed(0.6, 15, skip=range(4, 11)).empty(2).rule.pop() == 0   # 0.3 s with no reading: not seen whole


def test_nothing_while_the_presence_rule_is_busy_or_just_was_and_nothing_without_a_baseline():
    assert Line().feed(0.4, 15, busy=True).empty(2).rule.pop() == 0
    # the dip became a presence: the enter comes during the wait, and the walk-through is dropped
    assert Line().feed(0.6, 15).empty(0.3).empty(0.2, busy=True).empty(3).rule.pop() == 0
    # somebody who was here has just left: a dip in the next HOLD_OFF_MS is theirs
    line = Line().feed(5, 15, busy=True).empty(1.0).feed(0.4, 15).empty(2)
    assert line.rule.pop() == 0
    assert line.empty(HOLD_OFF_MS / 1000).feed(0.4, 15).empty(2).rule.pop() == 1
    assert Line().feed(0.4, 15, base=None).empty(2).rule.pop() == 0
    first = PassThrough()                             # the first readings after a start: the hold-off runs first
    for i in range(1, 60):
        first.on_reading(i * STEP, BASE - (15 if 5 <= i < 15 else 0), BASE, False)
    assert first.pop() == 0


def test_two_dips_inside_one_wait_are_one_crossing():
    assert Line().feed(0.3, 15).empty(0.4).feed(0.3, 15).empty(2).rule.pop() == 1
    assert Line().feed(0.3, 15).empty(2).feed(0.3, 15).empty(2).rule.pop() == 2


# ---- the whole brain on the gate layout ----

def kinds(events):
    return [e["kind"] for _, e in events if e["kind"] in WANTED]


def test_on_the_gate_a_walk_straight_through_is_one_passed_by_in_the_spots_zone():
    kit = cold_kit(seed=31)
    kit.play([(5, "nobody")])
    for _ in range(3):
        _, _, events = kit.play([(0.3, "still"), (6, "nobody")])
        assert kinds(events) == ["passed_by"], kinds(events)
        event = next(e for _, e in events if e["kind"] == "passed_by")
        assert event["info"] == {"zone": 1} and check.errors(event, "event") == []
    assert kit.brain.pred["present"] is False


def test_on_the_gate_a_stand_is_an_enter_and_an_exit_and_never_a_walk_through():
    kit = cold_kit(seed=32)
    kit.play([(5, "nobody")])
    for seconds in (2, 6, 1.5):
        _, _, events = kit.play([(seconds, "still"), (8, "nobody")])
        assert kinds(events) == ["enter", "exit"], (seconds, kinds(events))


def test_on_the_gate_the_alert_and_stepping_aside_and_back_give_no_walk_through():
    kit = cold_kit(seed=33)
    kit.play([(5, "nobody")])
    _, _, events = kit.play([(13, "still"), (2, "nobody"), (5, "still"), (8, "nobody")])
    said = kinds(events)
    assert "alert_on" in said and "checkin" in said and "passed_by" not in said, said
    _, _, events = kit.play([(120, "nobody")])
    assert kinds(events) == []


def test_on_the_gate_armed_a_walk_through_is_one_passed_by_and_a_stand_is_the_intrusion():
    kit = cold_kit(seed=34)
    kit.brain.on_cmd(cmd("arm", on=True))
    kit.play([(5, "nobody")])
    _, _, events = kit.play([(0.3, "still"), (8, "nobody")])
    assert kinds(events) == ["passed_by"], kinds(events)
    _, _, events = kit.play([(1.2, "still"), (8, "nobody")])      # long enough to be a presence: the armed rule's own
    assert kinds(events).count("passed_by") <= 1 and "intrusion" not in kinds(events), kinds(events)
    _, _, events = kit.play([(6, "still"), (8, "nobody")])
    assert [k for k in kinds(events) if k in ("intrusion", "passed_by")] == ["intrusion"]


def test_on_the_gate_nothing_is_said_while_a_baseline_is_taken_or_the_sensor_is_blind():
    kit = cold_kit(seed=35)
    kit.play([(5, "nobody")])
    kit.brain.on_cmd(cmd("baseline"))
    _, _, events = kit.play([(2, "nobody"), (0.3, "still"), (3, "nobody")])
    assert kit.brain.capture is not None and "passed_by" not in kinds(events)
    kit = cold_kit(seed=36)
    kit.play([(5, "nobody")])
    kit.brain.health.blind = True
    for i in range(100):                              # a crossing's readings, straight to the rule
        kit.brain._walked_through(int(kit.feed.t) + i * STEP, -47.0 - (15 if 10 <= i < 20 else 0))
    assert [e["kind"] for e in kit.brain.pop_events() if e["kind"] == "passed_by"] == []


def test_a_layout_with_no_presence_line_has_no_such_rule():
    desk = json.loads((Path(__file__).resolve().parents[2] / "radio" / "layouts" / "desk.json").read_text(encoding="utf-8"))
    assert "presence" not in desk and Brain(nodes=desk).passing is None and Kit().brain.passing is not None
