from pathlib import Path

import pytest

from proof import layout
from proof.walk import coach, script


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


def test_train_and_heldout_use_different_walk_orders(square):
    assert [s[0] for s in script("train")] != [s[0] for s in script("heldout")]
    assert layout.zones(square)[3][:2] == (0.5, 0.5)


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


# ---- the desk layout (#463): two zones on a strip ----

DESK = Path(__file__).parent / "fixtures" / "desk-nodes.json"


def desk_prompts(purpose):
    return [step[0] for step in script(purpose, layout.load(DESK))]


def test_desk_train_walk_names_left_and_right_at_their_centres():
    prompts = desk_prompts("train")
    text = " ".join(prompts)
    assert "zone 1 (Left), one step from the desk: x=0.4 m, y=0.3 m" in text
    assert "zone 2 (Right), one step from the desk: x=1.2 m, y=0.3 m" in text
    for word in ("square", "Bed", "Chair", "Hall", "Bathroom", "zone 3", "zone 4"):
        assert word not in text, word
    stands = [p for p in prompts if p.startswith("Stand still at")]
    assert [p.split("(")[1][:-2] for p in stands] == ["Left", "Right", "Left", "Right"]
    assert any("middle mark" in p and "x=0.8 m" in p for p in prompts)


def test_desk_orders_and_timings():
    steps = script("train", layout.load(DESK))
    visits = [s for s in steps if s[0].startswith("Stand still")]
    assert [s[1] for s in visits] == [10, 10, 10, 10, 8]          # 10 s per zone visit, 8 s on the middle mark
    assert all(s[1] == 5 for s in steps if s[0].startswith("Walk to"))
    heldout = [p for p in desk_prompts("heldout") if p.startswith("Stand still at")]
    assert [p.split("(")[1][:-2] for p in heldout] == ["Right", "Left", "Right", "Left"]
    crowd = script("crowd", layout.load(DESK))
    assert [s[3] for s in crowd if s[3] is not None] == [2, 1]   # truth for each stand


def test_desk_tray_is_placed_on_the_desk():
    prompts = desk_prompts("object")
    assert "Place the tray at T1 on the desk, then step back out of the strip." in prompts
    assert not any("square" in p for p in prompts)


def test_square_wording_is_unchanged(square):
    prompts = [s[0] for s in script("train", square)]
    assert prompts[0] == "Nobody inside the square. Step out completely."
    assert "Walk to the centre of zone 3 (Hall), x=0.5 m east, y=0.5 m north." in prompts


def test_the_layout_file_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("RADIO_SIGHT_NODES", str(DESK))
    assert "Left" in " ".join(s[0] for s in script("train"))
