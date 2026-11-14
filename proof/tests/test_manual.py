import pytest

from proof.manual import egress_bytes, update


def test_sourced_reading_and_zero_egress():
    proof = {"commit": "same", "measured_at": "original", "zone": {"total": 10}}
    result, evidence = update(proof, "same", "2026-11-14T21:00:00Z", "idle", 2.5, "USB meter", "0\n", "board/egress.sh count, 5 min")
    assert result["watts"]["idle"] == 2.5 and result["bytes_out"] == 0
    assert result["measured_at"] == "original" and evidence["source"] == "USB meter"
    assert "watts" not in proof


@pytest.mark.parametrize("watts", [-1, float("nan"), float("inf"), True])
def test_invalid_watts(watts):
    with pytest.raises(ValueError):
        update({}, "abc1234", "2026-11-14", "idle", watts, "meter")


def test_sources_are_mandatory():
    with pytest.raises(ValueError, match="source"):
        update({}, "abc1234", "2026-11-14", "idle", 2)
    with pytest.raises(ValueError, match="source"):
        update({}, "abc1234", "2026-11-14", egress="0")


@pytest.mark.parametrize("text", ["", "-1", "1.5", "egress: 12 bytes", "0\nerror"])
def test_egress_requires_successful_strict_stdout(text):
    with pytest.raises(ValueError):
        egress_bytes(text)


def test_mismatched_commit_or_meter_refused():
    with pytest.raises(ValueError, match="another commit"):
        update({"commit": "old", "bytes_out": 0}, "new", "2026-11-14", "idle", 2, "meter")
    with pytest.raises(ValueError, match="another meter"):
        update({"watts": {"source": "old", "idle": 2}}, "same", "2026-11-14", "teaching", 3, "new")
