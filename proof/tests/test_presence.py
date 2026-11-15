from collections import Counter
import pytest

from proof.presence import read_log, score_cycles, publish
from proof.presence_walk import run
from proof.score import confusion_report, presence_from_confusion, score, supported_fields
from proof.tests.test_score import FakeReplay, session


def fixtures():
    train = session("train","train",1)
    train["meta"]["walker"] = "training-walker"
    test = session("cycles")
    states = [dict(v=2,type="state",recv_t=t,src="live",cam="off",health={"status":"ok"},
                   model={"trained":True,"ver":"m1","train_sessions":["train"]},pred={"present":60000<=t<120000})
              for t in range(0,120001,1000)]
    return train,test,states,[(0,False),(60000,True),(120000,False)]


def test_binary_collapse_and_majority_baseline_use_the_same_denominator():
    c = confusion_report(Counter({(0,0):2,(0,1):1,(1,1):7}),{"zones":[{"id":1}]})
    assert c["majority_class_correct"] == 7 and c["total"] == 10 and c["chance"] == 0.5
    assert presence_from_confusion(c) == dict(correct=9,total=10,always_empty_correct=3,cycles=None,
        method="held-out 1 Hz camera windows; empty versus any zone; see PROOF.md")
    r = presence_from_confusion({"classes":[0,1,2],"counts":[[8,1,1],[2,2,3],[1,1,4]]})
    assert (r["correct"],r["total"],r["always_empty_correct"]) == (18,23,10)


def test_camera_presence_is_one_hz_not_every_overlapping_zone_window():
    r = score([session(zone=1)],FakeReplay((1,)*11))
    assert r["zone"]["total"] == 11 and r["presence"]["total"] == 2
    assert r["presence"]["cycles"] is None and r["presence"]["always_empty_correct"] == 0
    old = supported_fields(r,{"properties":{"zone":{"properties":{}}}})
    assert "presence" not in old and "majority_class_correct" not in old["zone"]
    new = supported_fields(r,{"properties":{"presence":{},"zone":{"properties":{"majority_class_correct":{}}}}})
    assert new["presence"] == r["presence"]


def test_independent_log_scores_seconds_and_does_not_double_count_states():
    train,test,states,log = fixtures()
    r = score_cycles(test,states+[states[0]],log,[train])
    assert (r["correct"],r["total"],r["always_empty_correct"],r["cycles"]) == (120,120,60,1)
    states[70]["pred"]["present"] = False
    states[10].update(pred=None,health={"status":"blind"})
    r = score_cycles(test,states,log,[train])
    assert (r["correct"],r["total"],r["always_empty_correct"]) == (118,119,59)
    assert score_cycles(test,[],log,[train])["total"] is None


@pytest.mark.parametrize("fault",["walker","sessions","camera","model","source"])
def test_cycles_refuse_leakage_unknown_provenance_and_camera_or_model_changes(fault):
    train,test,states,log = fixtures()
    if fault=="walker": test["meta"]["walker"] = "training-walker"
    if fault=="sessions": states[0]["model"]["train_sessions"] = ["unknown"]
    if fault=="camera": states[0]["cam"] = "on"
    if fault=="model": states[50]["model"]["ver"] = "m2"
    if fault=="source": states[0]["src"] = "sim"
    with pytest.raises(ValueError): score_cycles(test,states,log,[train])


def test_unused_old_training_file_does_not_change_the_recorded_models_provenance():
    train,test,states,log = fixtures()
    unused = session("old","train",1)
    assert score_cycles(test,states,log,[train,unused])["correct"] == 120


def test_csv_and_publishing_fail_closed(tmp_path):
    p = tmp_path/"truth.csv"
    p.write_text("recv_t,present\n0,0\n60000,1\n120000,0\n")
    assert read_log(p) == [(0,False),(60000,True),(120000,False)]
    p.write_text("recv_t,present\n0,0\n600,1\n1200,0\n")
    with pytest.raises(ValueError): read_log(p)
    train,test,states,log = fixtures()
    r = score_cycles(test,states,log,[train],allow_sim=True)
    with pytest.raises(ValueError,match="synthetic"): publish({},r,"abc1234",{"properties":{"presence":{}}})
    r["method"] = "held-out live fixture"
    with pytest.raises(ValueError,match="pending"): publish({},r,"abc1234",{})
    old = {"presence":{"correct":3}}
    assert publish(old,dict(r,correct=None,total=None),"abc1234",{"properties":{"presence":{}}}) == old


def test_guide_records_ten_confirmed_cycles_and_checks_readiness():
    clock,sent,marks = [0],[],[]
    def sleep(s): clock[0]+=s
    run("cycles","w2",sent.append,lambda t,p:marks.append((t,p)),ask=lambda _:None,say=lambda _:None,sleep=sleep,clock=lambda:clock[0])
    assert len(marks)==21 and marks[-1]==(1200000,0) and clock[0]==1200
    assert sent[0]["args"]["purpose"] == "heldout" and sent[-1]["cmd"]=="record_stop"
    marks.clear()
    with pytest.raises(ValueError): run("bad","w2",sent.append,lambda *r:marks.append(r),ask=lambda _:None,say=lambda _:None,sleep=sleep,ready=lambda:False)
    assert not marks and sent[-1]["cmd"] == "record_stop"


def test_pipeline_routes_csv_cycles_to_the_independent_scorer(tmp_path):
    import json
    from proof.run_all import plan
    for name,purpose in [("train","train"),("cycles","heldout")]:
        data = session(name,purpose)
        (tmp_path/(name+".jsonl")).write_text(json.dumps(data["meta"]))
    (tmp_path/"cycles.presence.csv").write_text("recv_t,present\n0,0\n60000,1\n120000,0\n")
    (tmp_path/"cycles.states.jsonl").write_text("")
    commands,_ = plan(tmp_path,tmp_path/"proof.json",tmp_path/"baseline.json",tmp_path/"PROOF.md")
    assert [c[2] for c in commands] == ["proof.presence","proof.render_table"]
    assert str(tmp_path/"cycles.presence.csv") in commands[0]


def test_presence_row_has_a_baseline_and_synthetic_rows_cannot_be_published():
    from proof.render_table import render
    document = "| Presence accuracy | pending | planned | __ | __ | __ |\n"
    data = {"presence":{"correct":19,"total":20,"always_empty_correct":10,"cycles":10,"method":"held-out cycles"},
            "measured_at":"2026-11-15T04:00:00Z","commit":"abc1234"}
    text = render(document,data)
    assert "19/20 (95.0%); always-empty baseline 10/20 (50.0%)" in text
    assert "20 sampled seconds; 10 cycles" in text
    data["presence"]["method"] = "SYNTHETIC SELF-TEST"
    with pytest.raises(ValueError): render(document,data)


def test_measured_proof_validation_resolves_contract_references_locally():
    import json
    from pathlib import Path
    from proof.score import validate_report
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root/"contracts/schemas/proof.json").read_text())
    proof = json.loads((root/"contracts/fixtures/valid_proof.json").read_text())
    validate_report(proof,schema)


def test_presence_can_be_the_first_measurement_without_inventing_other_numbers():
    import json
    from pathlib import Path
    from proof.provenance import empty_proof
    train,test,states,log = fixtures()
    result = score_cycles(test,states,log,[train])
    schema = json.loads((Path(__file__).resolve().parents[2]/"contracts/schemas/proof.json").read_text())
    schema["properties"]["presence"] = {"type":"object"}
    out = publish(empty_proof(),result,"abc1234",schema)
    assert out["presence"]["correct"] == 120 and out["zone"]["correct"] is None
    assert out["images_stored"] is out["bytes_out"] is None and out["commit"] == "abc1234"
