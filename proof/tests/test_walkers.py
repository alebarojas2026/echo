from types import SimpleNamespace

import pytest

from proof.score import BrainReplay, score, training_walkers
from proof.render_table import render
from proof.tests.test_score import FakeReplay, session
from proof.tests.test_render_table import DOCUMENT


def test_training_walker_is_refused_before_replaying():
    replay = FakeReplay()
    replay.train_walkers = {"w1"}
    replay.replay = lambda _: pytest.fail("leaked walker reached inference")
    with pytest.raises(ValueError, match="walker leakage: w1"):
        score([session()], replay)
    with pytest.raises(ValueError, match="walker leakage"):
        score([session()], replay, allow_sim=True)


def test_new_walker_reports_both_counts_without_changing_the_contract():
    replay, details = FakeReplay((4,)*11), {}
    replay.train_walkers = {"t1","t2"}
    result = score([session(zone=4)],replay,commit="abc1234",details=details)
    assert details["walkers"] == {"training":2,"heldout":1,"walker_independent":True}
    assert result["zone"]["walkers"] == 1 and "2 training walkers" in result["zone"]["method"]
    assert "1 walker the model never saw" in render(DOCUMENT,result)
    assert "2 training walkers" in render(DOCUMENT,result)
    assert "training_walkers" not in result["zone"]


@pytest.mark.parametrize("walker",[None,"","  ","none","unknown",42,False])
def test_missing_or_placeholder_heldout_identity_is_refused(walker):
    data = session()
    data["meta"]["walker"] = walker
    with pytest.raises(ValueError, match="walker pseudonym"):
        score([data],FakeReplay())


def test_identity_whitespace_cannot_bypass_overlap():
    data = session()
    data["meta"]["walker"] = " training-walker "
    with pytest.raises(ValueError, match="walker leakage"):
        score([data],FakeReplay())


@pytest.mark.parametrize("provenance",[None,"w1",[None]])
def test_unknown_training_provenance_is_not_an_empty_known_set(provenance):
    replay = FakeReplay()
    replay.train_walkers = provenance
    with pytest.raises(ValueError, match="walker"):
        score([session()],replay)


def test_adapter_uses_original_training_metas_without_editing_the_model():
    data = session("train","train",zone=4)
    data["meta"]["walker"] = "training-walker"
    model = SimpleNamespace(train_sessions=["train"],train_s=None)
    adapter = BrainReplay(model,{}, {},training=[data])
    assert adapter.train_walkers == {"training-walker"} and not hasattr(model,"train_walkers")
    adapter.replay = FakeReplay().replay
    assert score([session()],adapter)["zone"]["total"] == 11
    legacy = BrainReplay(model,{}, {})
    with pytest.raises(ValueError, match="provenance is missing"):
        score([session()],legacy)


def test_saved_model_metadata_and_original_training_metas_must_agree():
    data = session("train","train",zone=4)
    model = SimpleNamespace(train_sessions=["train"],train_s=None,train_walkers=["different"])
    with pytest.raises(ValueError, match="disagree"):
        BrainReplay(model,{}, {},training=[data])
    model.train_sessions = ["train","missing"]
    with pytest.raises(ValueError, match="metadata is missing"):
        BrainReplay(model,{}, {},training=[data])


def test_no_person_training_is_only_known_when_labels_confirm_it():
    data = session("empty","train")
    data["meta"]["walker"] = None
    assert training_walkers([data]) == set()
    data["messages"][1]["persons_in_frame"] = 1
    with pytest.raises(ValueError, match="walker pseudonym"):
        training_walkers([data])


def test_old_rows_are_not_relabelled_as_walker_independent():
    result = score([session()],FakeReplay(),commit="abc1234")
    result["zone"]["method"] = "held-out sessions"
    assert "the model never saw" not in render(DOCUMENT,result)


def test_cli_refuses_a_training_walker_before_writing_output(tmp_path,monkeypatch,capsys):
    import json
    import sys
    from proof.score import main
    for name,purpose in [("train","train"),("test","heldout")]:
        (tmp_path/(name+".jsonl")).write_text("\n".join(json.dumps(m) for m in session(name,purpose,4)["messages"]))
    baseline = tmp_path/"baseline.json"
    baseline.write_text("{}")
    output = tmp_path/"out.json"
    monkeypatch.setattr(sys,"argv",["score","--train",str(tmp_path/"train.jsonl"),"--heldout",str(tmp_path/"test.jsonl"),
                                    "--baseline",str(baseline),"--output",str(output)])
    with pytest.raises(SystemExit): main()
    assert "walker leakage: w1" in capsys.readouterr().err and not output.exists()


def test_post_lesson_walk_stays_out_of_the_unseen_walker_score(tmp_path):
    import json
    from proof.run_all import plan
    for name,purpose in [("train","train"),("test","heldout"),("after","heldout")]:
        (tmp_path/(name+".jsonl")).write_text(json.dumps(session(name,purpose)["meta"]))
    after = tmp_path/"after.jsonl"
    after.with_suffix(".trials.jsonl").write_text('{"kind":"walk"}')
    baseline = tmp_path/"baseline.json"
    baseline.write_text("{}")
    commands, missing = plan(tmp_path,tmp_path/"proof.json",baseline,tmp_path/"PROOF.md")
    score_command = commands[0]
    assert str(after) not in score_command and str(tmp_path/"test.jsonl") in score_command
    assert not any("trials.jsonl" in m for m in missing)
