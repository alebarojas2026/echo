import copy
import io
import pytest

from proof.security import analyze, publish
from proof.ablation import compare, subsets
from proof.security_walk import run, capture


def recorded(name="heldout", seconds=5, entry=True, src="sim"):
    meta = dict(v=2,type="meta",session=name,purpose="heldout",walker="w1",recv_t=0,src=src)
    labels = [dict(v=2,type="label",recv_t=t,src=src,present=bool(entry and 1000<=t<4000),
                   zone=1 if entry and 1000<=t<4000 else 0,persons_in_frame=int(entry and 1000<=t<4000),
                   clipped=False,mode="person",motion="still",foot_m=None)
              for t in range(0,seconds*1000+1,100)]
    states = [dict(v=2,type="state",recv_t=t,src=src,armed=True,health={"status":"ok"},
                   pred={"present":bool(entry and 1500<=t<4000),"kind":"person" if entry and 1500<=t<4000 else "none","zone":1})
              for t in range(0,seconds*1000+1,100)]
    return {"meta":meta,"messages":[meta]+labels}, states


def event(kind,t,identity): return dict(v=2,type="event",recv_t=t,src="sim",kind=kind,id=identity)


def test_entry_presence_and_armed_intrusion_with_intervals():
    session, states = recorded(seconds=8)
    result = analyze([(session,states+[event("intrusion",4600,"i")])])["detection"]
    assert result["entries"]==result["detected"]==result["armed_entries"]==result["intrusions"]==1
    assert result["ci95"][0]<1 and result["ci95"][1]==1


def test_missing_trace_clipped_truth_and_unarmed_stay_unknown():
    session, states = recorded()
    assert analyze([(session,[])])["detection"]["entries"] is None
    session["messages"][16]["clipped"] = True
    assert analyze([(session,states)])["detection"]["entries"] is None
    session, states = recorded()
    for state in states: state.pop("armed")
    assert analyze([(session,states)])["detection"]["armed_entries"] is None


def test_explicit_sensor_blind_is_a_missed_entry_not_empty():
    session, states = recorded()
    for state in states: state.update(pred=None,health={"status":"blind"})
    result = analyze([(session,states)])
    assert result["detection"]["detected"]==0
    assert result["false_alarms"]["duration_s"] is None


@pytest.mark.parametrize("latency,found",[(2000,1),(2100,0)])
def test_two_second_deadline_uses_recv_t(latency,found):
    session, states = recorded()
    for state in states:
        state["t"] = -100000
        state["pred"]["present"] = state["recv_t"]>=1000+latency
        state["pred"]["kind"] = "person" if state["pred"]["present"] else "none"
    assert analyze([(session,states)])["detection"]["detected"]==found


def test_false_events_per_hour_and_observed_duration():
    session, states = recorded(seconds=10,entry=False)
    events = [event("enter",1000,"e1"),event("enter",5000,"e2"),event("intrusion",2000,"i1")]
    result = analyze([(session,states+events+events)])["false_alarms"]
    assert result["duration_s"]==result["armed_duration_s"]==10
    assert result["presence_per_hour"]==720 and result["intrusions_per_hour"]==360


def test_duplicate_sessions_and_synthetic_proof_refused():
    session, states = recorded()
    with pytest.raises(ValueError): analyze([(session,states),(session,states)])
    report = dict(analyze([(session,states)]),fewer_devices=[])
    with pytest.raises(ValueError,match="pending"): publish({},report,[(session,states)],"abc1234",{})
    with pytest.raises(ValueError,match="synthetic"): publish({},report,[(session,states)],"abc1234",{"properties":{"security":{}}})


def test_unmeasured_report_renders_unknown_and_does_not_erase_prior_data():
    from proof.render_table import render
    report = dict(analyze([]),fewer_devices=[])
    text = render("# Proof\n",{"security":report})
    assert "Entry detection within 2 s | __ |" in text
    from proof.run_all import missing_metrics
    assert "entry detection" in missing_metrics({})
    assert "false presences per hour" not in missing_metrics({"security":{"false_alarms":{"presence_per_hour":0}}})
    old = {"security":dict(report,false_alarms={"duration_s":600,"presence_per_hour":0}),"commit":"same"}
    result = publish(old,report,[],"same",{"properties":{"security":{}}})
    assert result["security"]["false_alarms"]["duration_s"]==600


def layout():
    return {"nodes":[{"id":i,"roles":r} for i,r in [("router",["router"]),("rx",["receiver"]),("b1",[]),("b2",[]),("b3",[])]],
            "links":[{"id":f"{tx}>rx:ble","tx":tx,"rx":"rx"} for tx in ("router","b1","b2","b3")],
            "zones":[{"id":7,"name":"Desk Left"}]}


def test_subsets_follow_layout_ids_not_square_constants():
    groups = subsets(layout())
    assert [len(nodes) for _,nodes,_ in groups]==[5,4,2]
    assert groups[-1][2]==["router>rx:ble"]


def test_each_subset_retrains_without_heldout_or_excluded_links(monkeypatch):
    from brain import features as F
    from sklearn.ensemble import RandomForestClassifier
    original, columns = RandomForestClassifier.fit, []
    def fit(self,X,y):
        columns.append(len(X[0]))
        return original(self,X,y)
    monkeypatch.setattr(RandomForestClassifier,"fit",fit)
    test, _ = recorded()
    train = copy.deepcopy(test)
    train["meta"] = dict(train["meta"],session="train",purpose="train")
    for session in (train,test):
        for t in range(0,5001,100):
            for link in layout()["links"]:
                session["messages"].append(dict(type="rssi",recv_t=t,src="sim",link=link["id"],dbm=-60 if 1000<=t<4000 else -50))
    baseline = {link["id"]:-50 for link in layout()["links"]}
    result = compare([train],[test],baseline,layout(),allow_sim=True)
    assert columns == [links * len(F.STATS) for links in (4, 3, 1)]
    assert all(row["zone"]["total"] for row in result)
    with pytest.raises(ValueError): compare([test],[test],baseline,layout(),allow_sim=True)


@pytest.mark.parametrize("mode",["entries","empty","passes"])
def test_recording_scripts_use_layout_and_capture_only_messages(mode):
    now, commands, prompts = [0], [], []
    def sleep(seconds): now[0]+=seconds
    run("trial","w1",mode,layout(),commands.append,prompts.append,sleep,lambda:now[0],repeats=1)
    assert commands[0]["args"]["purpose"]=="heldout"
    assert commands[-1]["cmd"]=="record_stop" and commands[-3]["args"]=={"on":False}
    assert ("Desk Left" in " ".join(prompts)) == (mode!="empty")
    if mode=="empty": assert now[0]>=600
    out = io.StringIO()
    capture(['{"v":2,"type":"state","src":"sim"}','{"type":"camera-preview","image":"discard"}'],out,lambda:1)
    assert '"recv_t": 1000' in out.getvalue() and "image" not in out.getvalue()
