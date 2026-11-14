import pytest

from teacher.quality import report


def labels():
    return [dict(type="label", recv_t=t, present=True, zone=1, motion="still", clipped=False,
                 foot_m=[0.5, 1.5]) for t in range(0, 2001, 100)]


def test_rate_and_stationary_jitter():
    result = report(labels())
    assert result["labels_per_second"] == 10 and result["still_jitter_rms_m"] == 0
    assert not result["flags"]


def test_empty_and_clipped_shares_are_distinct():
    messages = labels()
    messages[0].update(present=False, foot_m=None)
    messages[1]["clipped"] = True
    result = report(messages)
    assert result["empty_frame_share"] == result["clipped_share"] == pytest.approx(1/21)


def test_missing_frames_and_jitter_flagged():
    messages = labels()
    for i, message in enumerate(messages):
        message["foot_m"][0] = 0.5 + (0.3 if i % 2 else -0.3)
    assert any("jitter" in flag for flag in report(messages)["flags"])
    assert report([messages[0], messages[-1]])["gaps_over_1s"] == 1
    assert report([])["labels_per_second"] is None


def test_simulated_empty_and_still_labels():
    from brain.tests.simdata import sim_to_v2
    empty = report(sim_to_v2("empty_room"))
    assert empty["empty_frame_share"] == 1 and empty["still_jitter_rms_m"] is None
    assert report(sim_to_v2("stand_still"))["labels"] > 0
