"""Inputs the brain passes on to the screen are checked first (issue #521)."""
from brain.core import Brain
from brain.tests.simdata import errors

T = 1_000_000


def test_a_malformed_cam_narration_or_record_start_never_reaches_the_screen():
    brain, sent = Brain(), []
    brain.to_bus = sent.append
    brain.on_message({"v": 2, "type": "cam", "t": T, "seq": 1, "src": "sim", "state": "on", "recv_t": T})
    brain.on_message({"v": 2, "type": "narration", "t": T, "seq": 2, "src": "sim", "text": "Someone walked in.",
                      "event_id": "e1", "source": "template", "gen_ms": 3, "recv_t": T})
    good = brain.state()
    assert good["cam"] == "on" and good["narration"]["text"] == "Someone walked in." and not errors(good)

    brain.on_message({"v": 2, "type": "cam", "t": T, "seq": 3, "src": "sim", "state": "exploded", "recv_t": T + 100})
    brain.on_message({"v": 2, "type": "narration", "t": T, "seq": 4, "src": "sim", "text": None, "event_id": 5,
                      "recv_t": T + 100})
    brain.on_message({"v": 2, "type": "narration", "t": T, "seq": 5, "src": "sim", "text": "x", "event_id": "e2",
                      "source": "a guess", "recv_t": T + 100})
    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "record_start", "args": {"session": {"a": 1}, "purpose": 7}})
    state = brain.state()
    assert state["cam"] == "on" and state["narration"] == good["narration"]     # the last good ones stay
    assert not errors(state)
    assert [e for e in brain.pop_events() if e["kind"] == "recording"] == [] and brain.want_session is None

    brain.on_cmd({"v": 2, "type": "cmd", "cmd": "record_start", "args": {"session": "s1", "purpose": "demo"}})
    events = [e for e in brain.pop_events() if e["kind"] == "recording"]
    assert len(events) == 1 and events[0]["info"] == {"on": True, "session": "s1"} and not errors(events[0])
