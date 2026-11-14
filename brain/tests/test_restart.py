"""Recordings and restarts: what the bus wrote is found again."""
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import Feed, cmd, record_to_disk

# ---- recordings and restarts ----

def test_recordings_made_before_a_restart_are_trained_on(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    record_to_disk(brain, feed, tmp_path, "s01", "empty_room", seed=2)
    record_to_disk(brain, feed, tmp_path, "s10", "zone_tour", walker="w1", seed=10)
    record_to_disk(brain, feed, tmp_path, "s20", "zone_tour", purpose="heldout", walker="w2", seed=11)
    (tmp_path / "s10.states.jsonl").write_text("{}\n")        # proof's capture files are not sessions

    again = Brain(sessions_dir=tmp_path)                       # restarted before anyone pressed Train
    assert again.base == brain.base and again.model is None
    again.on_cmd(cmd("train"))
    assert again.state()["model"]["train_sessions"] == ["s01", "s10"]   # never the held-out walk


def test_a_restart_in_the_middle_of_a_recording_still_trains_on_it(tmp_path):
    import json
    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    record_to_disk(brain, feed, tmp_path, "s01", "empty_room", seed=2)
    meta = {"session": "s10", "purpose": "train", "walker": "w1"}
    brain.on_cmd(cmd("record_start", **meta))
    msgs = sim_to_v2("zone_tour", seed=10, meta=meta, t0=feed.t)
    again = None
    with open(tmp_path / "s10.jsonl", "a") as f:               # the bus keeps writing all the while
        for i, m in enumerate(msgs):
            f.write(json.dumps(m) + "\n")
            if i == len(msgs) // 2:
                f.flush()
                again = Brain(sessions_dir=tmp_path)           # the brain alone is restarted
            (again or brain).on_message(m)
    again.on_cmd(cmd("record_stop"))
    again.on_cmd(cmd("train"))
    assert again.state()["model"]["train_sessions"] == ["s01", "s10"]


def test_a_training_recording_left_running_holds_nothing_in_memory(tmp_path):
    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    meta = {"session": "s10", "purpose": "train", "walker": "w1"}
    brain.on_cmd(cmd("record_start", **meta))
    (tmp_path / "s10.jsonl").write_text("")                    # the bus opened its file
    feed.play("zone_tour", seed=10, meta=meta)
    assert brain.open_session["meta"]["session"] == "s10" and brain.open_session["messages"] is None
    brain.on_cmd(cmd("record_stop"))
    assert brain.sessions["s10"]["messages"] is None and brain.sessions["s10"]["path"] == tmp_path / "s10.jsonl"
