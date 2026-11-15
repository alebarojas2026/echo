import pytest
import json
from pathlib import Path

from proof.security import analyze, hold_seconds, publish
from proof.render_table import render
from proof.tests.test_security import recorded, event


def trial(occupied_s=7, seconds=10, src="sim"):
    session, capture = recorded(seconds=seconds,src=src)
    for row in session["messages"]:
        if row.get("type") != "label": continue
        present = 1000 <= row["recv_t"] < 1000+occupied_s*1000
        row.update(present=present,zone=1 if present else 0,persons_in_frame=int(present))
    for row in capture:
        present = 1200 <= row["recv_t"] < 1000+occupied_s*1000
        row["pred"].update(present=present,kind="person" if present else "none")
    return session,capture


def test_delayed_intrusion_is_a_hit_and_never_also_a_false_alarm():
    session,capture = trial(occupied_s=3)
    capture += [event("intrusion",4600,"i"),event("intrusion",4600,"i")]
    result = analyze([(session,capture)])
    d = result["detection"]
    assert d["armed_entries"] == d["intrusions"] == 1 and d["within_s"] == 5 and d["hold_s"] == 3
    assert result["false_alarms"]["intrusions"] == 0
    text = render("# Proof\n",{"security":result,"commit":"abc1234","measured_at":"2026-11-15T03:00:00Z"})
    assert "Armed intrusion within 5 s" in text and "Entry detection within 2 s" in text


@pytest.mark.parametrize("offset,hits",[(3600,1),(5000,1),(5100,0)])
def test_configured_deadline_is_inclusive_and_uses_board_receive_time(offset,hits):
    s,c = trial()
    e = dict(event("intrusion",1000+offset,"i"),t=-100000)
    assert analyze([(s,c+[e])])["detection"]["intrusions"] == hits


def test_nondefault_hold_and_presence_deadline_are_separate():
    s,c = trial()
    for row in c:
        row["pred"].update(present=row["recv_t"]>=3100,kind="person")
    d = analyze([(s,c+[event("intrusion",6800,"i")])],{"armed":{"hold_s":4}})["detection"]
    assert d["within_s"] == 6 and d["intrusions"] == 1 and d["detected"] == 0


def test_short_walkthrough_counts_one_passed_by_and_no_intrusion_miss():
    s,c = trial(occupied_s=1.5)
    e = event("passed_by",2800,"p")
    r = analyze([(s,c+[e,e])])
    assert r["detection"]["entries"] == r["detection"]["detected"] == 1
    assert r["detection"]["armed_entries"] is r["detection"]["intrusions"] is None
    a = r["false_alarms"]
    assert a["intrusions"] == 0 and a["passed_by_events"] == 1
    assert a["passed_by_duration_s"] == 10 and a["passed_by_per_hour"] == 360


def test_gaps_or_missing_armed_coverage_do_not_fabricate_a_miss_or_zero_rate():
    s,c = trial()
    assert analyze([(s,[])])["false_alarms"]["passed_by_per_hour"] is None
    c = [row for row in c if not 3500<=row["recv_t"]<=5000]
    assert analyze([(s,c)])["detection"]["armed_entries"] is None


def test_passed_by_rate_uses_all_captured_armed_time_without_erasing_empty_evidence():
    s,c = trial(src="live")
    for row in s["messages"]:
        if row.get("type") == "label": row["clipped"] = True
    for row in c: row.update(pred=None,health={"status":"blind"})
    c.append(dict(event("passed_by",5000,"p"),src="live"))
    r = dict(analyze([(s,c)]),fewer_devices=[])
    assert r["false_alarms"]["duration_s"] is None and r["false_alarms"]["passed_by_events"] == 1
    prior = {"commit":"same","security":{"false_alarms":{"duration_s":600,"intrusions":0}}}
    out = publish(prior,r,[(s,c)],"same",{"properties":{"security":{}}})
    assert out["security"]["false_alarms"]["duration_s"] == 600
    assert out["security"]["false_alarms"]["passed_by_events"] == 1


@pytest.mark.parametrize("value",[-1,True,"3",float("nan"),float("inf")])
def test_invalid_hold_cannot_change_the_proof_window(value):
    with pytest.raises(ValueError): hold_seconds({"armed":{"hold_s":value}})


def test_offline_contract_validation_retains_device_subset_evidence():
    from jsonschema import ValidationError
    root = Path(__file__).resolve().parents[2]
    proof = json.loads((root/'contracts/fixtures/valid_proof.json').read_text())
    schema = json.loads((root/'contracts/schemas/proof.json').read_text())
    # Permit the pending optional rate fields while exercising the frozen device references.
    schema['properties']['security']['properties']['false_alarms']['additionalProperties'] = True
    report = dict(analyze([]),fewer_devices=[])
    out = publish(proof,report,[],proof['commit'],schema)
    assert out['security']['fewer_devices'] == proof['security']['fewer_devices']
    proof['security']['fewer_devices'][0]['links'] = ['not-a-layout-link']
    with pytest.raises(ValidationError): publish(proof,report,[],proof['commit'],schema)
