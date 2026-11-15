import io
import json
from pathlib import Path
import pytest

from proof.trials import analyze, publish, record
from proof.trials_walk import run


LAYOUT = {"zones":[{"id":7,"name":"Desk","still_alert_s":1}],
          "nodes":[{"id":"beacon-a","roles":["beacon"]}]}


def recording(purpose="crowd", src="sim", identity="s1"):
    meta = {"v":2,"type":"meta","recv_t":0,"src":src,"session":identity,"purpose":purpose}
    states = [{"v":2,"type":"state","recv_t":t,"src":src,"armed":True,"cam":"off",
               "health":{"status":"ok"},"pred":{"present":True,"zone":7},"alert":{"state":"none"},
               "model":{"trained":True,"train_sessions":["separate-lesson"]}}
              for t in range(0,20001,100)]
    return {"meta":meta,"messages":[meta]}, states, []


def annotation(kind,start,end,**extra):
    return dict(v=2,src="sim",session="s1",kind=kind,recv_t=start,end_t=end,**extra)


def event(kind,t,identity,node="beacon-a"):
    return dict(v=2,type="event",src="sim",kind=kind,recv_t=t,id=identity,info={"node":node})


def test_confirmed_passes_hourly_events_interval_and_still_alert():
    s,c,a = recording()
    a.extend([annotation("crowd",0,20000),annotation("pass",1000,6000),annotation("pass",10000,15000),annotation("still",0,20000,zone=7)])
    c += [event("intrusion",2000,"i1"),event("intrusion",8000,"i2"),event("intrusion",2000,"i1")]
    c[70]["alert"] = {"state":"check_on","zone":7}
    c.append(dict(event("alert_on",7000,"alert"),info={"zone":7}))
    r = analyze([(s,c,a)],LAYOUT)["passers_by"]
    assert (r["trials"],r["false_intrusions"],r["intrusion_events"],r["still_alerts"]) == (2,1,2,1)
    assert r["duration_s"] == 20 and r["intrusions_per_hour"] == 360
    assert r["ci95"][0] < 0.5 < r["ci95"][1]


def test_blind_and_missing_crowd_capture_never_become_successful_passes():
    s,c,a = recording()
    a.extend([annotation("crowd",0,20000),annotation("pass",0,20000)])
    for row in c: row.update(pred=None,health={"status":"blind"})
    r = analyze([(s,c,a)],LAYOUT)["passers_by"]
    assert r["trials"] is r["duration_s"] is r["intrusions_per_hour"] is None


def test_tamper_exact_deadline_node_matching_dedup_and_clean_exposure():
    s,c,a = recording("heldout")
    for row in c: row.update(pred=None,health={"status":"blind"})
    a.extend([annotation("tamper",0,20000),annotation("unplug",2000,8000,node="beacon-a"),annotation("unplug",10000,16000,node="beacon-a")])
    c += [event("tamper",7000,"hit"),event("tamper",7000,"hit"),event("tamper",12000,"wrong","other-node"),
          event("tamper",1000,"false"),event("tamper",15001,"late")]
    r = analyze([(s,c,a)],LAYOUT)["tamper"]
    assert (r["unplugs"],r["detected"],r["false_events"]) == (2,1,1)
    assert r["duration_s"] == 8 and r["false_per_hour"] == 450
    c = [row for row in c if not 3000 <= row["recv_t"] <= 4500]
    assert analyze([(s,c,a)],LAYOUT)["tamper"]["unplugs"] == 1


def test_lessons_are_timed_from_start_and_do_not_reuse_an_old_model():
    records = []
    for i,when in enumerate((3000,7000,None)):
        s,c,a = recording("train",identity=f"lesson-{i}")
        for row in c:
            row["t"] = -99999
            row["model"] = {"trained":True,"training":{"sessions":[s["meta"]["session"]],
                            "lesson":{"started_t":100,"fits":1,"of":10,"agree":8 if when and row["recv_t"]>=when else 7}}}
        records.append((s,c,a))
    r = analyze(records,LAYOUT)["lesson"]
    assert [row["ready_s"] for row in r["sessions"]] == [3,7,None]
    assert (r["shortest_s"],r["longest_s"],r["median_s"]) == (3,7,5)
    gapped = (records[0][0],[s for s in records[0][1] if not 1000<=s["recv_t"]<=2500],[])
    assert analyze([gapped],LAYOUT)["lesson"]["shortest_s"] is None
    for row in records[0][1]: row["model"]["training"]["sessions"] = ["old"]
    assert analyze([records[0]],LAYOUT)["lesson"]["shortest_s"] is None


def test_unplugged_walk_needs_independent_truth_and_camera_off():
    s,c,a = recording("heldout")
    a.append(annotation("walk",1000,3000,zone=7))
    r = analyze([(s,c,a)],LAYOUT)["lesson"]["unplugged_walk"]
    assert r["correct"] == r["total"] == 10
    c[20]["cam"] = "on"
    assert analyze([(s,c,a)],LAYOUT)["lesson"]["unplugged_walk"]["total"] is None
    c[20]["cam"] = "off"
    c[20]["model"]["train_sessions"].append("s1")
    assert analyze([(s,c,a)],LAYOUT)["lesson"]["unplugged_walk"]["total"] is None


def test_unknowns_schema_gate_synthetic_gate_and_duplicate_intervals():
    r = analyze([],LAYOUT)
    assert r["tamper"]["detected"] is None and r["lesson"]["median_s"] is None
    with pytest.raises(ValueError,match="pending"): publish({},r,[],"abc1234",{})
    with pytest.raises(ValueError,match="synthetic"): publish({},r,[recording()],"abc1234",{"properties":{"security_trials":{}}})
    live = recording(src="live")
    out = publish({},r,[live],"abc1234",{"properties":{"security_trials":{}}})
    assert out["security_trials"] == r and out["commit"] == "abc1234"
    s,c,a = recording()
    with pytest.raises(ValueError,match="duplicate"): analyze([(s,c,a),(s,c,a)],LAYOUT)
    a.extend([annotation("pass",0,5000),annotation("pass",4000,8000)])
    with pytest.raises(ValueError,match="overlapping"): analyze([(s,c,a)],LAYOUT)
    out = io.StringIO()
    assert record({"v":2,"type":"camera-preview","frame":"discard"},out,lambda:1) is None
    assert record(c[0],out,lambda:2)["recv_t"] == 2000 and "frame" not in out.getvalue()


def test_publish_preserves_device_evidence_using_local_contract_references():
    from jsonschema import ValidationError
    root = Path(__file__).resolve().parents[2]
    proof = json.loads((root/'contracts/fixtures/valid_proof.json').read_text())
    schema = json.loads((root/'contracts/schemas/proof.json').read_text())
    schema['properties']['security_trials'] = {}
    result = publish(proof,analyze([],LAYOUT),[],proof['commit'],schema)
    assert result['security']['fewer_devices'] == proof['security']['fewer_devices']
    from proof.provenance import empty_proof
    first = publish(empty_proof(),analyze([],LAYOUT),[],"abc1234",schema)
    assert first['zone']['correct'] is first['security_trials']['tamper']['unplugs'] is None
    proof['security']['fewer_devices'][0]['nodes'] = ['unknown-device']
    with pytest.raises(ValidationError): publish(proof,analyze([],LAYOUT),[],proof['commit'],schema)


@pytest.mark.parametrize("mode",["crowd","tamper","walk"])
def test_guides_save_only_confirmed_layout_markers_and_stop_recording(mode):
    now, sent, marks, prompts = [0],[],[],[]
    def sleep(s): now[0]+=s
    run("s1",mode,"w1",LAYOUT,sent.append,marks.append,prompts.append,prompts.append,sleep,lambda:now[0])
    assert sent[-1]["cmd"] == "record_stop"
    assert all(a["end_t"]>a["recv_t"] for a in marks)
    assert sum(a["kind"]=="pass" for a in marks) == (20 if mode=="crowd" else 0)
    assert sum(a["kind"]=="unplug" for a in marks) == (5 if mode=="tamper" else 0)
    if mode=="walk": assert "Desk" in " ".join(prompts) and not any(m["cmd"]=="train" for m in sent)


def test_interrupted_trial_is_not_confirmed_and_disarms():
    sent, marks = [],[]
    def cancel(_): raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt): run("s1","tamper","w1",LAYOUT,sent.append,marks.append,ask=cancel)
    assert not marks and sent[-2]["args"] == {"on":False} and sent[-1]["cmd"] == "record_stop"


def test_pipeline_discovers_sidecars_and_renders_unknowns(tmp_path):
    from proof.run_all import plan, missing_metrics
    from proof.render_table import render
    s,c,a = recording("train",identity="lesson")
    (tmp_path/"lesson.jsonl").write_text(json.dumps(s["meta"]))
    (tmp_path/"lesson.states.jsonl").write_text("")
    s,c,a = recording("crowd")
    (tmp_path/"crowd.jsonl").write_text(json.dumps(s["meta"]))
    (tmp_path/"crowd.states.jsonl").write_text("")
    (tmp_path/"crowd.trials.jsonl").write_text("")
    commands, missing = plan(tmp_path,tmp_path/"proof.json",tmp_path/"baseline.json",tmp_path/"PROOF.md")
    assert [c[2] for c in commands] == ["proof.trials","proof.render_table"]
    assert commands[0].count("--record") == 2 and "-" in commands[0]
    assert not any("trials.jsonl" in m for m in missing)
    text = render("# Proof\n",{"security_trials":analyze([],LAYOUT)})
    assert "Outside-only passes raising intrusion | __ |" in text and "Lesson median | __ |" in text
    assert "crowd intrusions per hour" not in missing_metrics({"security_trials":{"passers_by":{"intrusions_per_hour":0}}})


@pytest.mark.parametrize("kind",["tamper","unplug","walk"])
def test_specialized_heldout_trial_by_training_walker_stays_out_of_zone_score(tmp_path,kind):
    from proof.run_all import plan
    for identity,purpose,walker in [("train","train","w1"),("heldout","heldout","w2"),("tamper","heldout","w1")]:
        session,_,_ = recording(purpose,identity=identity)
        session["meta"]["walker"] = walker
        (tmp_path/(identity+".jsonl")).write_text(json.dumps(session["meta"]))
    tamper = tmp_path/"tamper.jsonl"
    tamper.with_suffix(".states.jsonl").write_text("")
    tamper.with_suffix(".trials.jsonl").write_text(json.dumps(dict(annotation(kind,1000,10000,node="beacon-a"),session="tamper")))
    baseline = tmp_path/"baseline.json"
    baseline.write_text("{}")
    commands,_ = plan(tmp_path,tmp_path/"proof.json",baseline,tmp_path/"PROOF.md")
    score = next(command for command in commands if command[2] == "proof.score")
    assert str(tamper) not in score and str(tmp_path/"heldout.jsonl") in score
    trials = next(command for command in commands if command[2] == "proof.trials")
    assert str(tamper) in trials and str(tamper.with_suffix(".trials.jsonl")) in trials
