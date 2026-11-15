import json

from proof.run_all import missing_metrics, plan


def recording(folder, identity, purpose):
    path = folder / (identity + ".jsonl")
    path.write_text(json.dumps(dict(v=2, type="meta", recv_t=0, src="live", session=identity, purpose=purpose)))
    return path


def test_missing_sessions_are_explicit(tmp_path):
    commands, missing = plan(tmp_path, tmp_path / "proof.json", tmp_path / "baseline.json", tmp_path / "PROOF.md")
    assert not commands
    assert any("purpose=train" in item for item in missing)
    assert any("purpose=heldout" in item for item in missing)
    assert any("baseline" in item for item in missing)


def test_plan_runs_stages_in_order_and_never_trains_on_heldout(tmp_path):
    train = recording(tmp_path, "train", "train")
    heldout = recording(tmp_path, "test", "heldout")
    recording(tmp_path, "object", "object")
    heldout.with_suffix(".states.jsonl").write_text("")
    heldout.with_suffix(".events.jsonl").write_text('{"v":2,"type":"state","recv_t":0}')
    (tmp_path / "proof-plan.json").write_text('{"negative_sessions":["test"]}')
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    commands, missing = plan(tmp_path, tmp_path / "proof.json", baseline, tmp_path / "PROOF.md", True)
    assert not missing
    assert [cmd[2] for cmd in commands] == ["proof.score", "proof.latency", "proof.false_alarms", "proof.security", "proof.render_table"]
    assert str(heldout) not in commands[0][commands[0].index("--train"):commands[0].index("--heldout")]
    assert "--on-board" in commands[0]


def test_zero_is_measured_and_null_is_missing():
    assert "measured egress bytes" not in missing_metrics({"bytes_out": 0})
    assert "training time on board" in missing_metrics({})


def recording_at(folder, identity, purpose, recv_t):
    path = folder / (identity + ".jsonl")
    path.write_text(json.dumps(dict(v=2, type="meta", recv_t=recv_t, src="live", session=identity, purpose=purpose)))
    return path


def test_sessions_from_before_the_current_place_are_left_out(tmp_path):
    old_train = recording_at(tmp_path, "sat-train", "train", 1000)
    old_test = recording_at(tmp_path, "sat-test", "heldout", 2000)
    train = recording_at(tmp_path, "sun-train", "train", 6000)
    heldout = recording_at(tmp_path, "sun-test", "heldout", 7000)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"t": 9000, "session": None, "links": {}}))   # an automatic baseline, later
    (tmp_path / "place.json").write_text(json.dumps({"t": 5000}))               # the place began here
    left_out = []
    commands, _ = plan(tmp_path, tmp_path / "proof.json", baseline, tmp_path / "PROOF.md", left_out=left_out)
    score = commands[0]
    assert str(train) in score and str(heldout) in score
    assert str(old_train) not in score and str(old_test) not in score
    assert sorted(left_out) == sorted([str(old_train), str(old_test)])


def test_without_place_json_the_baseline_time_is_the_cut_off(tmp_path):
    recording_at(tmp_path, "old", "train", 1000)
    recording_at(tmp_path, "old-test", "heldout", 1500)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"t": 5000, "session": None, "links": {}}))
    commands, missing = plan(tmp_path, tmp_path / "proof.json", baseline, tmp_path / "PROOF.md")
    assert not commands                                   # nothing from this place: nothing is scored
    assert any("purpose=train" in item for item in missing)


def test_the_recording_open_during_the_baseline_belongs_to_the_place(tmp_path):
    spanning = recording_at(tmp_path, "s1", "train", 4000)
    recording_at(tmp_path, "s2", "heldout", 6000)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"t": 5000, "session": "s1", "links": {}}))
    commands, _ = plan(tmp_path, tmp_path / "proof.json", baseline, tmp_path / "PROOF.md")
    assert str(spanning) in commands[0]


def test_a_file_that_cannot_be_read_is_named_and_the_rest_still_run(tmp_path):
    train = recording_at(tmp_path, "train", "train", 6000)
    heldout = recording_at(tmp_path, "test", "heldout", 7000)
    twice = recording_at(tmp_path, "twice", "train", 6500)
    twice.write_text(twice.read_text() + "\n" + twice.read_text())      # a session name used twice: two metas
    (tmp_path / "cut.jsonl").write_text('{"v":2,"type":"meta","recv_')   # a line cut short by a crash
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    commands, missing = plan(tmp_path, tmp_path / "proof.json", baseline, tmp_path / "PROOF.md")
    assert str(train) in commands[0] and str(heldout) in commands[0] and str(twice) not in commands[0]
    assert sum("readable session file" in item for item in missing) == 2
