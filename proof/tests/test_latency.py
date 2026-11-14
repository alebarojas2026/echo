import pytest

from proof.latency import analyze, update_proof
from proof.score import object_evidence, read_baseline


def logs(src="live"):
    messages = [dict(v=2, type="rssi", src=src, recv_t=t, t=-999, dbm=-50) for t in (100, 200)]
    state = dict(v=2, type="state", src=src, model={"ms_per_decision": 99})
    states = [dict(recv_t=120, input_recv_t=100, decision_ms=2, state=state),
              dict(recv_t=220, input_recv_t=100, decision_ms=2, state=state),
              dict(recv_t=240, input_recv_t=200, decision_ms=4, state=state)]
    return messages, states


def test_deduplicated_explicit_spans_and_first_state():
    result = analyze(*logs())
    assert result["ms_per_decision"] == {"p50": 3, "p95": 3.9}
    assert result["end_to_end_ms"] == {"p50": 30, "p95": 39}
    assert result["reflected_readings"] == 2


def test_rolling_median_in_plain_state_is_not_a_decision_sample():
    messages, states = logs()
    plain = [dict(states[0]["state"], recv_t=120)]
    assert analyze(messages, plain)["ms_per_decision"] == {"p50": None, "p95": None}
    assert analyze(messages, plain)["reflected_readings"] == 0


def test_negative_clock_or_invalid_span_rejected():
    messages, states = logs()
    states[0]["recv_t"] = 99
    with pytest.raises(ValueError):
        analyze(messages, states)


def test_sim_does_not_update_proof():
    messages, states = logs("sim")
    with pytest.raises(ValueError):
        update_proof({}, analyze(messages, states), messages, states, "abc1234")


def test_baseline_contract_artifact(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text('{"t":123,"session":null,"links":{"a":{"base_dbm":-50,"expected_hz":10}}}')
    assert read_baseline(path) == ({"a": -50}, {"a": 10})


def test_object_stability_uses_half_second_means():
    radio = [dict(type="rssi", link="a", recv_t=t, dbm=-55 + (2 if i % 2 else -2))
             for i, t in enumerate(range(0, 2500, 50))]
    assert object_evidence(radio, 2500, {"a": -50})
