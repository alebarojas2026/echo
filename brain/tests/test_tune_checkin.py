"""brain/tune_checkin.py: reading a recorded wave session (the tool for gate 8, issue #223)."""
import json

import pytest

from brain import tune_checkin as T
from brain.alert import CHECKIN_LINK
from brain.tests.simdata import T0_MS, sim_to_v2


def write(tmp_path, msgs, name="gate8-wave"):
    path = tmp_path / f"{name}.jsonl"
    path.write_text("".join(json.dumps(m) + "\n" for m in msgs))
    return path


def test_spans_split_a_recording_into_waves_and_quiet_time():
    waves, quiet = T.spans(1000, 61_000, [10, 20], 2.5, None)
    assert waves == [(11_000, 13_500), (21_000, 23_500)]
    assert quiet == [(1000, 11_000), (14_500, 21_000), (24_500, 61_000)]   # 1 s kept clear after each wave
    _, walking = T.spans(1000, 61_000, [10, 20], 2.5, 40)
    assert walking == [(41_000, 61_000)]


def test_swings_count_readings_above_and_below_the_median():
    flat = [(t, -50.0) for t in range(0, 3000, 100)]
    assert T.swings(flat, 0, 3000) == {"readings": 30, "above": 0, "below": 0, "max_up_db": 0.0, "max_down_db": 0.0}
    dips = [(t, -50.0 - (4.0 if 2000 <= t < 2300 else 0.0)) for t in range(0, 3000, 100)]
    s = T.swings(dips, 2000, 3000)
    assert s["below"] == 3 and s["above"] == 0 and s["max_down_db"] == -4.0   # a wave that only dips


def test_the_sim_wave_is_found_and_a_stricter_rule_can_be_tried():
    msgs = sim_to_v2("wave_checkin", seed=1)              # the wave is at 14-16.5 s
    waves, quiet = T.spans(T0_MS, msgs[-1]["recv_t"], [14.0], 2.5, None)
    assert T.tally(T.replay(msgs), waves, quiet) == {"caught": 1, "waves": 1, "false": 0, "false_per_min": 0.0}
    assert T.tally(T.replay(msgs, cross_db=6.0), waves, quiet)["caught"] == 0    # 4 dB swings never cross 6 dB
    rows = T.grid(msgs, waves, quiet)
    assert len(rows) == 5 * 5 * 3 * 3 and rows[0]["caught"] == 1 and rows[0]["false"] == 0


def test_only_a_live_recording_is_reported_without_the_flag(tmp_path, capsys):
    path = write(tmp_path, sim_to_v2("wave_checkin", seed=1))
    with pytest.raises(SystemExit, match="not a live recording"):
        T.main([str(path), "--waves", "14"])
    T.main([str(path), "--waves", "14", "--allow-sim", "--top", "3"])
    out = capsys.readouterr().out
    assert out.startswith("NOT A MEASUREMENT") and "wave  1 at   14.0 s" in out and "check-in: yes" in out
    assert "1 of 1 waves, 0 check-ins outside them" in out


def test_a_live_recording_prints_the_per_wave_counts(tmp_path, capsys):
    live = [dict(m, src="live") for m in sim_to_v2("wave_checkin", seed=1)]   # stands in for the board's file
    T.main([str(write(tmp_path, live)), "--waves", "14", "--walk-from", "17"])
    out = capsys.readouterr().out
    assert "NOT A MEASUREMENT" not in out and f"{CHECKIN_LINK}:" in out and "grid, best 12" in out
