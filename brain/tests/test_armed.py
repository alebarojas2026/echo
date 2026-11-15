"""Armed mode (CONTRACTS.md sections 5 and 6): arm, disarm, one intrusion per entry."""
import json

from brain.alert import Armed
from brain.core import NODES_JSON, Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import cmd, taught


def person(zone=2):
    return {"present": True, "kind": "person", "zone": zone}


NOBODY = {"present": False, "kind": "none", "zone": 0}
OBJECT = {"present": False, "kind": "object", "zone": 0}


def feed(rule, preds):
    return [z for z in (rule.on_pred(p) for p in preds) if z is not None]


def test_somebody_still_there_3_s_after_appearing_is_one_intrusion():
    rule = Armed()
    assert rule.arm(True) and not rule.arm(True)                 # arming twice changes nothing
    assert feed(rule, [NOBODY] * 20) == []
    assert feed(rule, [person(2)] * 6) == []                     # the 6th of 10: they have appeared; the 3 s start
    assert feed(rule, [person(2)] * 29) == []
    assert feed(rule, [person(2)]) == [2]                        # 30 decisions later: one intrusion, naming the zone
    assert feed(rule, [person(2)] * 200) == []                   # staying raises nothing more
    assert feed(rule, [NOBODY] * 3 + [person(2)] * 60) == []     # a 0.3 s gap is not leaving
    assert feed(rule, [NOBODY] * 10 + [person(1)] * 36) == [1]   # gone, then somebody again: a second one
    assert rule.pop_passed() == []


def test_a_walk_through_is_passed_by_and_never_an_intrusion():
    rule = Armed()
    rule.arm(True)
    assert feed(rule, [NOBODY] * 20 + [person(1)] * 15 + [NOBODY] * 20) == []   # 1.5 s in the strip
    assert rule.pop_passed() == [1] and rule.pop_passed() == []                 # one passed_by, naming the zone
    assert feed(rule, [person(2)] * 50 + [NOBODY] * 20) == [2]                  # a 5 s step-in: one intrusion
    assert rule.pop_passed() == []                                              # ... and leaving after it is nothing new
    assert feed(rule, ([person(1)] * 20 + [NOBODY] * 20) * 3) == [] and rule.pop_passed() == [1, 1, 1]


def test_the_hold_comes_from_the_layout_file_and_0_means_at_once():
    from brain import settings as S
    assert S.hold_s({}) == 3.0 and S.hold_s({"armed": {"hold_s": 4}}) == 4.0 and S.hold_s({"armed": {}}) == 3.0
    for bad in ("3", True, -1, 600):
        try:
            S.hold_s({"armed": {"hold_s": bad}})
            raise AssertionError(bad)
        except ValueError:
            pass
    busy = Armed(hold_s=4)                                       # a very busy aisle
    busy.arm(True)
    assert feed(busy, [person(2)] * 45) == [] and feed(busy, [person(2)]) == [2]
    at_once = Armed(hold_s=0)
    at_once.arm(True)
    assert feed(at_once, [person(2)] * 5) == [] and feed(at_once, [person(2)]) == [2]
    assert feed(at_once, [NOBODY] * 20) == [] and at_once.pop_passed() == []
    doc = json.loads(NODES_JSON.read_text(encoding="utf-8"))
    assert Brain().armed.hold == 30                              # no armed block in the file: 3 s
    assert Brain(nodes={**doc, "armed": {"hold_s": 4}}).armed.hold == 40


def test_a_flickering_decision_is_nothing_and_an_object_never_is():
    rule = Armed()
    rule.arm(True)
    assert feed(rule, ([person()] + [NOBODY] * 3) * 20) == []    # 1 in 4: never the majority
    assert feed(rule, [OBJECT] * 100) == []
    assert feed(rule, [dict(person(), kind="object")] * 100) == []
    assert rule.pop_passed() == []                               # neither an intrusion nor a passed_by


def test_nothing_is_raised_unless_armed_and_arming_with_somebody_inside_raises_it():
    rule = Armed()
    assert feed(rule, [person(4)] * 50) == []                    # not armed: people are welcome
    rule.arm(True)                                               # armed with that person still there
    assert feed(rule, [person(4)] * 36) == [4]
    rule.arm(False)
    assert feed(rule, [NOBODY] * 20 + [person(4)] * 60) == []
    rule.arm(True)
    assert feed(rule, [NOBODY] * 20 + [person(4)] * 10) == []
    rule.arm(False)                                              # disarmed during the wait: nothing is said
    assert feed(rule, [person(4)] * 40 + [NOBODY] * 20) == [] and rule.pop_passed() == []


def test_null_pred_raises_nothing_and_does_not_count_as_leaving_or_as_staying():
    rule = Armed()
    rule.arm(True)
    assert feed(rule, [person(3)] * 36) == [3]
    assert feed(rule, [None] * 50 + [person(3)] * 30) == []      # blind for 5 s, the same person still there
    assert feed(rule, [NOBODY] * 10 + [None] * 50) == []         # they leave; then blind
    assert feed(rule, [person(3)] * 5 + [None] + [person(3)] * 5) == []   # the count starts again after a null
    assert feed(rule, [person(3)] * 20 + [None] * 100) == []     # appeared, 1.9 s into the wait, then blind for 10 s
    assert feed(rule, [person(3)] * 10) == []                    # blind time is not time spent there
    assert feed(rule, [person(3)]) == [3]
    assert rule.pop_passed() == []


def test_the_brain_arms_disarms_and_raises_one_intrusion_when_somebody_walks_in():
    brain, feed_ = taught()
    brain.pop_events()
    assert "armed" not in brain.state()                          # missing means false
    brain.on_cmd(cmd("arm", on=True))
    brain.on_cmd(cmd("arm", on=True))
    assert brain.state()["armed"] is True
    feed_.play("empty_room", seed=90)
    feed_.play("stand_still", seed=91)                           # walks in, stands 20 s, walks out
    feed_.play("tray_t1", seed=92)                               # an object is not an intruder
    events = brain.pop_events()
    kinds = [(e["kind"], e["info"]) for e in events if e["kind"] in ("armed", "disarmed", "intrusion", "passed_by")]
    assert kinds[0] == ("armed", {}) and [k for k, _ in kinds].count("armed") == 1
    intrusions = [info for k, info in kinds if k == "intrusion"]
    assert len(intrusions) == 1 and intrusions[0]["zone"] in (1, 2, 3, 4)
    assert "passed_by" not in [k for k, _ in kinds]              # they stayed: an intrusion, not a passer-by
    t_in = next(e["t"] for e in events if e["kind"] == "enter")
    t_alarm = next(e["t"] for e in events if e["kind"] == "intrusion")
    assert 2500 <= t_alarm - t_in <= 4500                        # about 3 s after they appeared

    brain.on_cmd(cmd("reset"))                                   # between judges: reset disarms
    assert "armed" not in brain.state()
    assert [e["kind"] for e in brain.pop_events() if e["kind"] in ("armed", "disarmed", "reset")] == ["disarmed", "reset"]
    feed_.play("stand_still", seed=93)
    assert "intrusion" not in [e["kind"] for e in brain.pop_events()]
    brain.on_cmd(cmd("arm", on="yes"))                           # not a boolean: ignored
    assert "armed" not in brain.state()


def test_no_intrusion_while_the_sensor_is_blind():
    brain, feed_ = taught()
    brain.on_cmd(cmd("arm", on=True))
    feed_.play("empty_room", seed=90)
    brain.pop_events()
    states = []
    feed_.play("dropped_link", seed=54, states=states)           # a link dies while somebody is in the square
    events = brain.pop_events()
    assert "blind_on" in [e["kind"] for e in events]
    blind = [e["t"] for e in events if e["kind"] == "blind_on"][0]
    clear = [e["t"] for e in events if e["kind"] == "blind_off"]
    for e in events:
        if e["kind"] == "intrusion":
            assert e["t"] < blind or (clear and e["t"] > clear[0])   # never from a decision nobody may see
    assert all(s["armed"] is True for _, s in states)            # still armed; the screen shows SENSOR BLIND
