"""The demo rehearsal: the fake feed through the real bus and brain code, beat by beat."""
import pytest

from sim import rehearse

# Beats the real stack does not show yet. Each needs an issue; keep this empty for the demo.
KNOWN_FAILING = set()


@pytest.fixture(scope="module")
def results():
    return rehearse.rehearse()


def test_every_beat_is_checked_in_runbook_order(results):
    assert [name for name, _, _ in results] == [
        "setup: baseline", "setup: training", "empty room", "walk in", "tour: zone 3 Hall",
        "tour: zone 4 Bathroom", "tour: zone 2 Chair", "tour: zone 1 Bed", "no-movement alert", "wave check-in",
        "camera unplugged, radio only", "tray near the router", "advice to move the router", "router moved",
        "router back home", "reset between judges"]


def test_every_beat_shows_up(results):
    failed = {name for name, passed, _ in results if not passed}
    assert failed <= KNOWN_FAILING, f"beats that did not show: {sorted(failed - KNOWN_FAILING)}"


def test_beats_show_in_good_time(results):
    shown = {name: s for name, passed, s in results if passed and s is not None}
    assert "advice to move the router" in shown        # #260: state carries the brain's advice
    assert 10 <= shown["no-movement alert"] <= 13      # zone 4's limit is 10 s of standing still
    assert shown["wave check-in"] <= 2.5               # within the 2.5 s wave
    assert all(shown[name] <= 2 for name in shown if name.startswith("tour") or name == "walk in")


def test_a_broken_beat_fails_by_name(capsys, monkeypatch):
    path, commands, beats = rehearse.demo_script()
    broken = dict(path, waves=[])   # nobody waves, so the check-in never happens
    results = rehearse.rehearse((broken, commands, beats))
    failed = {name for name, passed, _ in results if not passed}
    assert "wave check-in" in failed and "no-movement alert" not in failed
    monkeypatch.setattr(rehearse, "rehearse", lambda: results)
    assert rehearse.main([]) == 1
    out = capsys.readouterr().out
    assert "FAIL  wave check-in" in out and "PASS  no-movement alert  shown after" in out
    assert "failed: " in out.splitlines()[-1] and "wave check-in" in out.splitlines()[-1]
