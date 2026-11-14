import pytest

from proof.false_alarms import analyze, update_proof


def session():
    return [dict(v=2, type="label", recv_t=t, src="live", zone=0, present=False,
                 clipped=False, mode="person", motion=None) for t in range(0, 2001, 100)]


def state(t):
    return dict(v=2, type="state", recv_t=t, src="live")


def event(t, identity="one"):
    return dict(v=2, type="event", recv_t=t, src="live", id=identity, kind="checkin")


def test_continuous_capture_is_clipped_to_session():
    result = analyze(session(), [state(-1000), event(-500), event(500), event(2500), state(3000)], zones={})
    assert result["counts"]["checkin"] == 1
    assert result["observed_minutes"] == pytest.approx(2/60)
    assert result["false_alarms_per_min"] == 30


def test_outside_event_cannot_hide_inside_event_with_same_id():
    result = analyze(session(), [state(-1000), event(-500), event(500), state(3000)], zones={})
    assert result["counts"]["checkin"] == 1


def test_partial_overlap_uses_only_observed_overlap():
    result = analyze(session(), [state(-1000), event(500), state(1000)], zones={})
    assert result["observed_minutes"] == pytest.approx(1/60)
    assert result["false_alarms_per_min"] == 60


@pytest.mark.parametrize("capture", [[state(-2000), state(-1000)], [state(3000), state(4000)], []])
def test_missing_and_disjoint_capture_is_still_refused(capture):
    with pytest.raises(ValueError):
        analyze(session(), capture, zones={})


def test_touching_boundary_is_not_observation():
    result = analyze(session(), [state(-1000), state(0)], zones={})
    assert result["observed_minutes"] == 0
    assert result["false_alarms_per_min"] is None


def test_synthetic_capture_cannot_update_measured_proof():
    capture = [dict(state(-1000), src="sim"), state(3000)]
    result = analyze(session(), capture, zones={})
    with pytest.raises(ValueError, match="only live"):
        update_proof({}, result, session(), capture, "abc1234")
