"""router_moved only takes a spot from nodes.json."""
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import cmd
from brain.tests.simdata import errors


def test_router_moved_to_an_unknown_spot_is_ignored_and_state_stays_valid():
    brain = Brain()
    for m in sim_to_v2("empty_room", seed=1)[:200]:
        brain.on_message(m)
    for args in ({"spot": "nowhere"}, {}, {"spot": None}, {"spot": "S-home"}, {"spot": ["S-W30"]}):
        brain.on_cmd({"v": 2, "type": "cmd", "cmd": "router_moved", "args": args})
        state = brain.state()
        assert state["router"] == "S-home" and not errors(state), args
    assert "router_moved" not in [e["kind"] for e in brain.events]

    brain.on_cmd(cmd("router_moved", spot="S-W30"))            # a real spot still works
    state = brain.state()
    assert state["router"] == "S-W30" and not errors(state)
    assert [e["kind"] for e in brain.events].count("router_moved") == 1
