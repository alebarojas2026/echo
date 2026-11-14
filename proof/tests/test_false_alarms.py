import pytest

from proof.false_alarms import analyze, analyze_many, update_proof


@pytest.fixture(autouse=True)
def zones(monkeypatch):
    monkeypatch.setattr("proof.false_alarms.load_zones", lambda: {1: 60, 2: None, 3: None, 4: 10})


def labels(zone=0, seconds=2):
    return [dict(type="label", src="live", recv_t=t, mode="person", present=bool(zone), zone=zone,
                 motion="still" if zone else None, clipped=False) for t in range(0, seconds * 1000 + 1, 100)]


def event(kind, t=500, zone=4):
    return dict(type="event", src="live", recv_t=t, id=kind, kind=kind, info={"zone": zone})


def test_counts_and_duplicate_captures():
    events = [event(k) for k in ("checkin", "alert_on", "object_on")]
    result = analyze(labels(), events + events)
    assert result["counts"] == dict(checkin=1, alert_on=1, object_on=1)
    assert result["false_alarms_per_min"] == 90


def test_expected_no_movement_alert_is_not_false():
    assert analyze(labels(4, 12), [event("alert_on", 11000)])["counts"]["alert_on"] == 0
    assert analyze(labels(4, 12), [event("alert_on", 9000)])["counts"]["alert_on"] == 1
    assert analyze(labels(4, 12), [event("alert_on", 11000, zone=1)])["counts"]["alert_on"] == 1


def test_unknown_and_moving_time_excluded():
    assert analyze([], [event("object_on")])["false_alarms_per_min"] is None
    messages = labels(4)
    for m in messages:
        m["motion"] = "moving"
    assert analyze(messages, [event("checkin")])["observed_minutes"] == 0


def test_gap_and_clipping_do_not_count_as_observed_empty():
    messages = labels()
    for m in messages:
        m["clipped"] = True
    assert analyze(messages, [event("alert_on")])["observed_minutes"] == 0
    assert analyze([labels()[0], labels()[-1]], [event("alert_on")])["observed_minutes"] == 0


def test_sim_paths_and_no_simulated_proof():
    from brain.tests.simdata import sim_to_v2
    messages = sim_to_v2("empty_room")
    result = analyze(messages, [])
    assert result["observed_minutes"] > 0 and result["false_alarms_per_min"] == 0
    with pytest.raises(ValueError):
        update_proof({}, result, messages, [], "abc1234")


def test_still_sim_path_has_observation():
    from brain.tests.simdata import sim_to_v2
    assert analyze(sim_to_v2("stand_still"), [])["observed_minutes"] > 0


def test_multiple_sessions_aggregate_counts_and_exposure():
    result = analyze_many([(labels(), [event("checkin")]), (labels(seconds=4), [])])
    assert result["counts"]["checkin"] == 1
    assert result["false_alarms_per_min"] == 10


def test_changed_zone_limits_and_provenance():
    assert analyze(labels(4, 12), [event("alert_on", 11000)], zones={4: 20})["counts"]["alert_on"] == 1
    data = labels()
    with pytest.raises(ValueError, match="another commit"):
        update_proof({"zone": {"total": 10}, "commit": "old"}, analyze(data, []), data, [], "new")
