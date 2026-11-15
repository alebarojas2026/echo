import json
from pathlib import Path

import pytest

from proof.false_alarms import analyze
from proof.manual import capture_egress, update
from proof.provenance import prepare_update
from proof.run_all import missing_metrics, plan
from proof.score import merge_scored, score
from proof.tests.test_score import FakeReplay, session
from teacher.quality import report


def camera():
    return [dict(type="label", recv_t=t, frame=i, src="live", zone=0, present=False,
                 clipped=False, mode="person", motion=None) for i, t in enumerate(range(0, 2001, 100))]


def test_1_missing_wrong_clock_and_partial_capture():
    with pytest.raises(ValueError, match="missing events"):
        analyze(camera(), [], zones={})
    with pytest.raises(ValueError, match="outside"):
        analyze(camera(), [dict(type="state", recv_t=3600000)], zones={})
    result = analyze(camera(), [dict(type="state", recv_t=t) for t in (500, 1500)], zones={})
    assert result["observed_minutes"] == pytest.approx(1/60)


@pytest.mark.parametrize("purpose,events", [("train", "{}"), ("object", "{}"), ("heldout", "")])
def test_2_invalid_negative_recordings_are_missing(tmp_path, purpose, events):
    (tmp_path / "one.jsonl").write_text(json.dumps(dict(v=2, type="meta", recv_t=0, session="one", purpose=purpose)))
    (tmp_path / "one.events.jsonl").write_text(events)
    (tmp_path / "proof-plan.json").write_text('{"negative_sessions":["one"]}')
    commands, missing = plan(tmp_path, tmp_path / "proof.json", tmp_path / "baseline.json", tmp_path / "PROOF.md")
    assert any("negative" in m or "captured negative events" in m for m in missing)
    assert not any("proof.false_alarms" in c for c in commands)


def test_3_missing_walker_cannot_claim_independence():
    data = session()
    data["meta"].pop("walker")
    with pytest.raises(ValueError, match="walker pseudonym"):
        score([data], FakeReplay())


@pytest.mark.parametrize("source,duration", [("datasheet typical", 300), ("rated spec", 300),
                                          ("https://example.com", 300), ("USB meter", 299)])
def test_4_unmeasured_or_short_power_is_refused(source, duration):
    with pytest.raises(ValueError):
        update({}, "abc1234", "2026-11-14", "idle", 3.5, source, duration_s=duration)


def test_5_egress_is_read_from_board_command(monkeypatch):
    def unavailable(): raise ValueError("not on board")
    monkeypatch.setattr("proof.provenance.require_board", unavailable)
    with pytest.raises(ValueError, match="not on board"):
        capture_egress()
    monkeypatch.setattr("proof.provenance.require_board", lambda: None)
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        return "12\n"
    monkeypatch.setattr("proof.manual.subprocess.check_output", execute)
    assert capture_egress() == "12\n"
    assert calls[0][-1] == "count" and Path(calls[0][-2]).parts[-2:] == ("board", "egress.sh")


def test_6_zero_watts_is_not_a_board_measurement():
    with pytest.raises(ValueError, match="positive"):
        update({}, "abc1234", "2026-11-14", "idle", 0, "USB meter", duration_s=300)


def test_7_empty_proof_takes_new_provenance():
    out = prepare_update({"commit": "old", "measured_at": "old", "bytes_out": None}, "new", "new date")
    assert out["commit"] == "new" and out["measured_at"] == "new date"


def test_8_manual_uses_actual_date_and_ignores_local_log():
    out, evidence = update({}, "abc1234", "2026-11-13", "idle", 3.5, "USB meter", duration_s=300)
    assert out["measured_at"] == evidence["measured_at"] == "2026-11-13"
    assert "/proof.manual.jsonl" in (Path(__file__).parents[1] / ".gitignore").read_text()


def test_9_rescore_preserves_fields_it_cannot_measure():
    old = {"commit": "same", "watts": {"idle": 3}, "bytes_out": 0, "false_alarms_per_min": 0.5}
    out = merge_scored(old, score([], FakeReplay(), commit="same"))
    for key in ("watts", "bytes_out", "false_alarms_per_min"):
        assert out[key] == old[key]
    with pytest.raises(ValueError):
        merge_scored(old, score([], FakeReplay(), commit="different"))


def test_10_all_unmeasured_proof_strip_fields_remain_missing():
    missing = missing_metrics({})
    for name in ("idle power measurement", "teaching power measurement", "measured images stored", "installed model inventory"):
        assert name in missing


def test_11_session_horizon_includes_leading_camera_silence():
    labels = [dict(m, recv_t=55000 + i * 100) for i, m in enumerate(camera())]
    messages = [dict(type="meta", recv_t=0)] + labels + [dict(type="rssi", recv_t=60000)]
    result = report(messages)
    assert result["labels_per_second"] == pytest.approx(len(labels)/60)
    assert result["gaps_over_1s"] == 2


def test_12_single_frame_gap_count_is_unknown():
    assert report(camera()[:1])["gaps_over_1s"] is None


def test_13_duplicate_labels_do_not_double_frame_rate():
    messages = camera()
    assert report(messages + messages)["labels_per_second"] == report(messages)["labels_per_second"]


def test_false_event_cli_requires_board_before_proof_write(tmp_path, monkeypatch):
    from proof.false_alarms import main
    labels, capture, output = (tmp_path / name for name in ("session.jsonl", "events.jsonl", "proof.json"))
    labels.write_text("\n".join(json.dumps(m) for m in camera()))
    capture.write_text("\n".join(json.dumps(dict(type="state", src="live", recv_t=t)) for t in (0, 2000)))
    output.write_text("{}")
    monkeypatch.setattr("proof.false_alarms.load_zones", lambda: {})
    monkeypatch.setattr("sys.argv", ["false_alarms", str(labels), str(capture), "--proof", str(output)])
    def blocked(): raise ValueError("requires board")
    monkeypatch.setattr("proof.false_alarms.require_board", blocked)
    with pytest.raises(ValueError, match="requires board"):
        main()
    assert output.read_text() == "{}"
