"""Shuffled trials and the empty hour (#780): scoring, the tuning/report wall, and the wording."""
import json

import pytest

from proof import shuffled as S


def recording(tmp_path, role="report", mode="trials", rows=(), src="live", name="r1"):
    header = {"type": "header", "session": name, "mode": mode, "role": role, "walker": "w1", "seed": 7,
              "src": src, "commit": "abc", "t": 0}
    path = tmp_path / f"{name}.shuffled.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in [header, *rows]))
    return path


def states(t0, t1, present=lambda t: False):
    return [{"type": "state", "t": t, "present": bool(present(t)), "kind": "person" if present(t) else "none",
             "hidden": False, "src": "live"} for t in range(t0, t1, 100)]


def trial(n, kind, t0):
    return {"type": "trial", "n": n, "kind": kind, "t0": t0, "t1": t0 + 20_000}


def test_the_plan_has_16_12_12_and_depends_on_the_seed():
    a, b = S.plan(1), S.plan(2)
    assert len(a) == 40 and {k: a.count(k) for k in S.KINDS} == {"stand": 16, "empty": 12, "walk": 12}
    assert a != b and a == S.plan(1) and a != sorted(a)


def test_a_stand_trial_is_detected_with_its_time():
    rows = [trial(1, "stand", 0), *states(0, 25_000, lambda t: 2_400 <= t < 20_000)]
    r = S.score({"session": "x", "role": "report", "mode": "trials"}, rows)
    assert r["stand"] == {"n": 1, "detected": 1, "seconds": [2.4]} and r["median_detect_s"] == 2.4


def test_a_stand_trial_nobody_saw_is_missed_and_two_blips_are_not_a_detection():
    h = {"session": "x", "role": "report", "mode": "trials"}
    missed = S.score(h, [trial(1, "stand", 0), *states(0, 25_000)])
    assert missed["stand"]["detected"] == 0 and missed["stand"]["n"] == 1
    blips = S.score(h, [trial(1, "stand", 0), *states(0, 25_000, lambda t: t in (3_000, 3_100, 9_000))])
    assert blips["stand"]["detected"] == 0                     # under 3 states in a row


def test_an_empty_trial_counts_a_false_presence_once_and_the_rest_is_not_scored():
    h = {"session": "x", "role": "report", "mode": "trials"}
    clean = S.score(h, [trial(1, "empty", 0), *states(0, 25_000, lambda t: t >= 21_000)])   # only in the rest
    assert clean["empty"] == {"n": 1, "false": 0}
    false = S.score(h, [trial(1, "empty", 0), *states(0, 25_000, lambda t: 5_000 <= t < 6_000 or 9_000 <= t < 9_500)])
    assert false["empty"] == {"n": 1, "false": 1}


@pytest.mark.parametrize("events, outcome", [(["passed_by"], "passed_by"), (["intrusion"], "intrusion"),
                                             (["passed_by", "intrusion"], "intrusion"), ([], "nothing"),
                                             (["enter", "exit"], "nothing")])
def test_a_walk_through_comes_out_as_passed_by_intrusion_or_nothing(events, outcome):
    h = {"session": "x", "role": "report", "mode": "trials"}
    rows = [trial(1, "walk", 0), *states(0, 25_000), *[{"type": "event", "t": 21_000, "kind": k} for k in events]]
    walk = S.score(h, rows)["walk"]                             # an event in the 5 s rest still belongs to the walk
    assert walk["n"] == 1 and walk[outcome] == 1 and sum(walk[k] for k in ("passed_by", "intrusion", "nothing")) == 1


def test_a_trial_with_no_state_heard_is_left_out_and_said():
    h = {"session": "x", "role": "report", "mode": "trials"}
    r = S.score(h, [trial(1, "stand", 0), trial(2, "empty", 25_000), *states(25_000, 50_000)])
    assert r["unheard_trials"] == 1 and r["stand"]["n"] == 0 and r["empty"]["n"] == 1
    assert any("left out" in line for line in S.lines(r))


def test_a_whole_run_of_40():
    rows, t = [], 0
    for n, kind in enumerate(S.plan(3), 1):
        rows.append(trial(n, kind, t))
        seen = (lambda t0: (lambda x: t0 + 2_000 <= x < t0 + 20_000))(t) if kind == "stand" and n != 5 else (lambda x: False)
        rows += states(t, t + 25_000, seen)
        if kind == "walk":
            rows.append({"type": "event", "t": t + 6_000, "kind": "passed_by"})
        t += 25_000
    r = S.score({"session": "x", "role": "report", "mode": "trials"}, rows)
    missed = int(S.plan(3)[4] == "stand")
    assert r["trials"] == 40 and r["stand"]["n"] == 16 and r["stand"]["detected"] == 16 - missed
    assert r["empty"] == {"n": 12, "false": 0} and r["walk"]["passed_by"] == 12


def test_the_empty_hour_reports_the_length_actually_recorded():
    h = {"session": "e", "role": "report", "mode": "empty"}
    rows = [{"type": "span", "t0": 0, "t1": 3_600_000},
            *states(0, 1_800_000, lambda t: 600_000 <= t < 601_000 or 900_000 <= t < 900_200),   # stopped at 30 min
            {"type": "event", "t": 600_500, "kind": "intrusion"}, {"type": "event", "t": 5_000_000, "kind": "intrusion"}]
    r = S.score(h, rows)
    assert r["recorded_minutes"] == pytest.approx(30.0, abs=0.1)
    assert r["false_presences"] == 2 and r["false_intrusions"] == 1        # every empty-space blip counts
    assert r["false_presences_per_hour"] == pytest.approx(4.0, abs=0.05)
    assert "30.0 minutes actually recorded" in S.lines(r)[0]


def test_exact_interval_values():
    low, high = S.exact_interval(15, 16)
    assert low == pytest.approx(0.6977, abs=0.001) and high == pytest.approx(0.9984, abs=0.001)
    assert S.exact_interval(0, 12)[0] == 0.0 and S.exact_interval(0, 12)[1] == pytest.approx(0.2646, abs=0.001)
    assert S.exact_interval(16, 16) == (pytest.approx(0.794, abs=0.001), 1.0)
    assert S.exact_interval(0, 0) is None


def test_the_range_is_said_in_plain_words():
    assert S.plain_range(15, 16, "detected") == \
        "15 of 16 detected; with this few trials the true rate is probably between 69% and 100%"
    assert S.plain_range(16, 16, "detected").endswith("between 79% and 100%")
    assert S.plain_range(0, 12, "empty trials showed someone").endswith("between 0% and 27%")
    assert "nothing to report" in S.plain_range(0, 0, "detected")


def test_report_refuses_a_tuning_recording_and_tune_refuses_a_report_one(tmp_path, capsys):
    rows = [trial(1, "stand", 0), *states(0, 25_000, lambda t: t >= 2_000)]
    tuning = recording(tmp_path, role="tuning", rows=rows, name="t1")
    report = recording(tmp_path, role="report", rows=rows, name="r1")
    with pytest.raises(SystemExit) as e:
        S.main(["report", str(tuning)])
    assert "tuning recording" in str(e.value) and "never reported" in str(e.value)
    with pytest.raises(SystemExit) as e:
        S.main(["tune", str(report)])
    assert "report recording" in str(e.value)
    S.main(["tune", str(tuning)])
    S.main(["report", str(report)])
    out = capsys.readouterr().out
    assert out.count("1 of 1 detected") == 2


def test_report_refuses_a_recording_that_is_not_live_or_has_no_role(tmp_path):
    sim = recording(tmp_path, src="sim", name="s1")
    with pytest.raises(SystemExit) as e:
        S.main(["report", str(sim)])
    assert "not a live recording" in str(e.value)
    bad = tmp_path / "x.shuffled.jsonl"
    bad.write_text(json.dumps({"type": "header", "session": "x"}) + "\n")
    with pytest.raises(ValueError):
        S.read(bad)


def test_the_guide_cues_one_trial_at_a_time_and_marks_each(monkeypatch):
    said, marks, now = [], [], [0.0]
    S.guide(["stand", "empty", "walk"], marks.append, say=said.append,
            sleep=lambda s: now.__setitem__(0, now[0] + s), clock=lambda: now[0])
    assert [m["kind"] for m in marks] == ["stand", "empty", "walk"]
    assert [(m["t0"], m["t1"]) for m in marks] == [(0, 20_000), (25_000, 45_000), (50_000, 70_000)]
    assert said[0] == "Trial 1 of 3. Step onto the spot and stand still." and said[1] == "Step away from the spot."
    assert not any("empty" in s.lower() and "Trial 1" in s for s in said)    # the order isn't announced ahead


def test_states_are_kept_reduced_and_stamped_on_our_clock():
    kept = []
    S.keep({"v": 2, "type": "state", "t": 5, "src": "live", "pred": {"present": True, "kind": "person"}}, kept.append,
           clock=lambda: 12.5)
    S.keep({"v": 2, "type": "state", "t": 6, "src": "live", "pred": None}, kept.append, clock=lambda: 12.6)
    S.keep({"v": 2, "type": "event", "kind": "intrusion", "info": {"zone": 1}}, kept.append, clock=lambda: 12.7)
    S.keep({"v": 2, "type": "event", "kind": "trained"}, kept.append, clock=lambda: 12.8)
    assert kept == [{"type": "state", "t": 12500, "present": True, "kind": "person", "hidden": False, "src": "live"},
                    {"type": "state", "t": 12600, "present": False, "kind": None, "hidden": True, "src": "live"},
                    {"type": "event", "t": 12700, "kind": "intrusion"}]


def test_gaps_and_hidden_predictions_do_not_claim_a_clean_trial_or_hour():
    h = {'session':'e', 'role':'report', 'mode':'empty'}
    rows = [{'type':'span','t0':0,'t1':3600000}, *states(0,1000), *states(3599000,3600000)]
    result = S.score(h, rows)
    assert result['recorded_minutes'] == 0  # 1.8 seconds, not an hour
    h['mode'] = 'trials'
    result = S.score(h,[trial(1,'empty',0), *states(0,1000), *states(19000,20000)])
    assert result['empty']['n'] == 0 and result['unheard_trials'] == 1
    hidden = states(0,20000)
    hidden[100]['hidden'] = True
    assert S.score(h,[trial(1,'empty',0),*hidden])['unheard_trials'] == 1
    assert S.present_runs([{'t':0,'present':True},{'t':10000,'present':True},{'t':19000,'present':True}],0,20000) == []
    assert S.present_runs(states(0,300,lambda t:True),0,1000) == []
    assert S.present_runs(states(0,400,lambda t:True),0,1000) == [0]


def test_live_header_cannot_hide_simulated_states(tmp_path):
    path = recording(tmp_path, rows=[dict(states(0,100)[0],src='sim')])
    with pytest.raises(SystemExit, match='non-live'):
        S.main(['report',str(path)])


def test_reporting_rejects_a_reversed_capture_clock(tmp_path):
    path = recording(tmp_path, rows=list(reversed(states(0,1000))))
    with pytest.raises(SystemExit, match='capture clock'):
        S.main(['report',str(path)])


def test_detection_latency_uses_the_even_sample_median():
    rows = [trial(1,'stand',0), *states(0,20000,lambda t:t>=1000),
            trial(2,'stand',25000), *states(25000,45000,lambda t:t>=28000)]
    result = S.score({'session':'r','role':'report','mode':'trials'},rows)
    assert result['median_detect_s'] == 2


def test_even_one_false_presence_state_counts_on_an_empty_trial():
    result = S.score({'session':'e','role':'report','mode':'trials'},
                     [trial(1,'empty',0),*states(0,20000,lambda t:t==5000)])
    assert result['empty'] == {'n':1,'false':1}


@pytest.mark.parametrize("missing", ["clearance", "gap", "unknown"])
def test_walk_requires_coverage_until_its_last_possible_alert(missing):
    heard = states(0, 25_000)
    if missing == "clearance":
        heard = [s for s in heard if s["t"] < 20_000]
    elif missing == "gap":
        heard = [s for s in heard if not 22_000 <= s["t"] < 23_000]
    else:
        heard[220]["hidden"] = True
    rows = [trial(1, "walk", 0), *heard]
    result = S.score({"session": "w", "role": "report", "mode": "trials"}, rows)
    assert result["unheard_trials"] == 1
    assert result["walk"] == {"n": 0, "passed_by": 0, "intrusion": 0, "nothing": 0}


@pytest.mark.parametrize("kind", ["stand", "empty"])
def test_other_trials_do_not_require_the_unscored_clearance(kind):
    rows = [trial(1, kind, 0), *states(0, 20_000)]
    result = S.score({"session": "w", "role": "report", "mode": "trials"}, rows)
    assert result["unheard_trials"] == 0 and result[kind]["n"] == 1


def test_a_late_walk_alert_belongs_only_to_the_observed_previous_trial():
    rows = [trial(1, "walk", 0), trial(2, "walk", 25_000), *states(0, 50_000),
            {"type": "event", "t": 24_900, "kind": "intrusion"},
            {"type": "event", "t": 25_000, "kind": "passed_by"}]
    result = S.score({"session": "w", "role": "report", "mode": "trials"}, rows)
    assert result["unheard_trials"] == 0
    assert result["walk"] == {"n": 2, "passed_by": 1, "intrusion": 1, "nothing": 0}
