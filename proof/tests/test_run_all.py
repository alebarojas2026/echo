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
    assert [cmd[2] for cmd in commands] == ["proof.score", "proof.latency", "proof.false_alarms", "proof.render_table"]
    assert str(heldout) not in commands[0][commands[0].index("--train"):commands[0].index("--heldout")]
    assert "--on-board" in commands[0]


def test_zero_is_measured_and_null_is_missing():
    assert "measured egress bytes" not in missing_metrics({"bytes_out": 0})
    assert "training time on board" in missing_metrics({})
