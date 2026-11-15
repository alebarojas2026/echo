"""Armed mode (CONTRACTS.md sections 5 and 6): arm, disarm, one intrusion per entry."""
from brain.alert import Armed
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import cmd, taught


def person(zone=2):
    return {"present": True, "kind": "person", "zone": zone}


NOBODY = {"present": False, "kind": "none", "zone": 0}
OBJECT = {"present": False, "kind": "object", "zone": 0}


def feed(rule, preds):
    return [z for z in (rule.on_pred(p) for p in preds) if z is not None]


def test_one_intrusion_per_entry_not_one_per_decision():
    rule = Armed()
    assert rule.arm(True) and not rule.arm(True)                 # arming twice changes nothing
    assert feed(rule, [NOBODY] * 20) == []
    assert feed(rule, [person(2)] * 5) == []                     # 5 of 10 is not the majority yet
    assert feed(rule, [person(2)]) == [2]                        # the 6th: one intrusion, naming the zone
    assert feed(rule, [person(2)] * 200) == []                   # staying raises nothing more
    assert feed(rule, [NOBODY] * 3 + [person(2)] * 30) == []     # a 0.3 s gap is not leaving
    assert feed(rule, [NOBODY] * 10 + [person(1)] * 10) == [1]   # gone, then somebody again: a second one


def test_a_flickering_decision_is_not_an_intrusion_and_an_object_never_is():
    rule = Armed()
    rule.arm(True)
    assert feed(rule, ([person()] + [NOBODY] * 3) * 20) == []    # 1 in 4: never the majority
    assert feed(rule, [OBJECT] * 100) == []
    assert feed(rule, [dict(person(), kind="object")] * 100) == []


def test_nothing_is_raised_unless_armed_and_arming_with_somebody_inside_raises_it():
    rule = Armed()
    assert feed(rule, [person(4)] * 50) == []                    # not armed: people are welcome
    rule.arm(True)                                               # armed with that person still there
    assert feed(rule, [person(4)] * 10) == [4]
    rule.arm(False)
    assert feed(rule, [NOBODY] * 20 + [person(4)] * 20) == []


def test_null_pred_raises_nothing_and_does_not_count_as_leaving():
    rule = Armed()
    rule.arm(True)
    assert feed(rule, [person(3)] * 10) == [3]
    assert feed(rule, [None] * 50 + [person(3)] * 30) == []      # blind for 5 s, the same person still there
    assert feed(rule, [NOBODY] * 10 + [None] * 50) == []         # they leave; then blind
    assert feed(rule, [person(3)] * 5 + [None] + [person(3)] * 5) == []   # the count starts again after a null
    assert feed(rule, [person(3)]) == [3]                        # 6 real decisions since: raised now


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
    kinds = [(e["kind"], e["info"]) for e in brain.pop_events() if e["kind"] in ("armed", "disarmed", "intrusion")]
    assert kinds[0] == ("armed", {}) and [k for k, _ in kinds].count("armed") == 1
    intrusions = [info for k, info in kinds if k == "intrusion"]
    assert len(intrusions) == 1 and intrusions[0]["zone"] in (1, 2, 3, 4)

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
