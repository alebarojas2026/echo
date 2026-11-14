import pytest

from proof.walk import CENTRES, coach, script


@pytest.mark.parametrize("purpose", ["train", "heldout", "object", "crowd"])
def test_every_script_records_with_metadata_and_order(purpose):
    now, messages, prompts = [0], [], []
    def sleep(seconds): now[0] += seconds
    coach("unique-session", purpose, "w1", messages.append, prompts.append, sleep, lambda: now[0])
    assert messages[0]["cmd"] == "record_start"
    assert messages[0]["args"] == {"session": "unique-session", "purpose": purpose, "walker": "w1"}
    assert messages[-1]["cmd"] == "record_stop"
    assert messages[-2]["args"] == {"mode": "off"}
    step_prompts = [p for p in prompts if p.startswith("\n")]
    assert [p.split("\n")[1] for p in step_prompts] == [step[0] for step in script(purpose)]
    assert now[0] == sum(step[1] for step in script(purpose))
    assert [m["seq"] for m in messages] == list(range(1, len(messages)+1))
    assert script(purpose)[0][1] == 20


def test_train_and_heldout_use_different_walk_orders():
    assert [s[0] for s in script("train")] != [s[0] for s in script("heldout")]
    assert CENTRES[3][:2] == (0.5, 0.5)


def test_object_evaluation_stays_heldout_and_uses_a_new_trial():
    now, messages = [0], []
    def sleep(seconds): now[0] += seconds
    coach("heldout-object", "heldout", "w1", messages.append, lambda _: None, sleep, lambda: now[0], object_trial=True)
    assert messages[0]["args"]["purpose"] == "heldout"
    assert any(m["args"] == {"mode": "object"} for m in messages)


def test_interrupt_stops_recording_and_turns_labels_off():
    messages = []
    def interrupted(_): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        coach("interrupted", "train", "w1", messages.append, lambda _: None, interrupted, lambda: 0)
    assert messages[-2]["args"] == {"mode": "off"}
    assert messages[-1]["cmd"] == "record_stop"


@pytest.mark.parametrize("identity", ["../existing", "", "x"*65])
def test_invalid_session_ids_rejected_before_commands(identity):
    messages = []
    with pytest.raises(ValueError):
        coach(identity, "train", "w1", messages.append)
    assert not messages
