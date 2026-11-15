"""state.chain: the board's chain head, copied from the bus (CONTRACTS.md section 13)."""
import pytest

from brain import core
from brain.core import Brain
from contracts import check

T0 = 1_763_149_500_000
HASH = "1a2b3c4d" + "ef" * 28


def head(**over):
    return {"v": 2, "type": "chain_head", "t": T0, "seq": 4127, "src": "live", "hash": HASH, "recv_t": T0 + 3,
            "verified": True, "witnesses_ok": 2, "witnesses": 2, **over}


def test_no_head_heard_means_no_chain_in_state():
    assert "chain" not in Brain().state()


def test_the_head_is_copied_into_state_and_fits_the_contract():
    brain = Brain(clock=lambda: T0 + 100)
    brain.on_message(head())
    state = brain.state()
    assert state["chain"] == {"seq": 4127, "hash8": "1a2b3c4d", "verified": True, "witnesses_ok": 2, "witnesses": 2}
    assert check.errors(state) == []
    brain.on_message(head(seq=4133, hash="9f" * 32, witnesses_ok=1))
    assert brain.state()["chain"] == {"seq": 4133, "hash8": "9f9f9f9f", "verified": True, "witnesses_ok": 1, "witnesses": 2}


def test_verified_is_true_only_once_the_board_has_said_so():
    brain = Brain(clock=lambda: T0 + 100)
    bare = {k: v for k, v in head().items() if k not in ("verified", "witnesses_ok", "witnesses")}
    brain.on_message(bare)                                    # before the board's first check
    assert brain.state()["chain"] == {"seq": 4127, "hash8": "1a2b3c4d", "verified": False, "witnesses_ok": 0, "witnesses": 0}
    brain.on_message(head(verified=False))
    assert brain.state()["chain"]["verified"] is False


def test_a_head_is_not_a_reading():
    brain = Brain()
    brain.on_message(head(recv_t=T0 + 99_000))
    brain.on_message({"v": 2, "type": "chain_witness", "t": T0, "seq": 4127, "src": "live", "node": "pi5", "hash": HASH,
                      "sig": "A" * 86 + "==", "recv_t": T0 + 99_000})
    assert brain.feed_t == Brain().feed_t                     # the clock that follows the feed did not move
    state = brain.state()
    assert state["links"] == [] and state["pred"] is None and brain.pop_events() == []


@pytest.mark.parametrize("bad", [{"seq": "12"}, {"seq": -1}, {"hash": "abc"}, {"hash": None}, {"witnesses": "two"},
                                 {"witnesses_ok": -1}, {"seq": True}])
def test_a_head_that_is_not_one_is_dropped(bad):
    brain = Brain(clock=lambda: T0)
    brain.on_message(head(**bad))
    assert "chain" not in brain.state()


def test_the_chain_leaves_state_when_no_head_has_come_for_15_s(monkeypatch):
    now = [500.0]
    monkeypatch.setattr(core.time, "monotonic", lambda: now[0])
    brain = Brain(clock=lambda: T0)
    brain.on_message(head())
    now[0] += 15.0
    assert "chain" in brain.state()
    now[0] += 0.1
    assert "chain" not in brain.state()                       # the web server stopped: nothing stale is shown
    brain.on_message(head())
    assert "chain" in brain.state()
