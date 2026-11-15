"""The demo rehearsal: the fake feed through the real bus and brain code, beat by beat."""
import pytest

from sim import rehearse

# Beats the real stack does not show yet. Each needs an issue; keep this empty for the demo.
KNOWN_FAILING = set()


@pytest.fixture(scope="module")
def results():
    return rehearse.rehearse()


def test_every_beat_is_checked_in_runbook_order(results):
    tour = [f"tour: zone {z} {rehearse.LAYOUT.names[z]}" for z in rehearse.TOUR]   # the square: 3 Hall, 4, 2, 1
    assert [name for name, _, _ in results] == [
        "setup: baseline", "setup: training", "empty room", "walk in", *tour, "no-movement alert", "wave check-in",
        "camera unplugged, radio only", "tray near the router", "advice to move the router", "router moved",
        "router back home", "reset between judges",
        "recap after the reset"]


def test_every_beat_shows_up(results):
    failed = {name for name, passed, _ in results if not passed}
    assert failed <= KNOWN_FAILING, f"beats that did not show: {sorted(failed - KNOWN_FAILING)}"


def test_beats_show_in_good_time(results):
    shown = {name: s for name, passed, s in results if passed and s is not None}
    assert "advice to move the router" in shown        # #260: state carries the brain's advice
    # The alert zone's limit is 10 s of standing still. The brain can start counting in the last steps
    # of the walk there: 9.8 s after the judge stops, on the strip.
    assert 9.5 <= shown["no-movement alert"] <= 13
    assert shown["wave check-in"] <= 2.5               # within the 2.5 s wave
    assert all(shown[name] <= 2 for name in shown if name.startswith("tour") or name == "walk in")


def test_a_broken_beat_fails_by_name(capsys, monkeypatch):
    path, commands, beats = rehearse.demo_script()
    broken = dict(path, waves=[])   # nobody waves, so the check-in never happens
    results = rehearse.rehearse((broken, commands, beats))
    failed = {name for name, passed, _ in results if not passed}
    assert "wave check-in" in failed and "no-movement alert" not in failed
    monkeypatch.setattr(rehearse, "rehearse", lambda *a, **k: results)
    assert rehearse.main([]) == 1
    out = capsys.readouterr().out
    assert "FAIL  wave check-in" in out and "PASS  no-movement alert  shown after" in out
    assert "failed: " in out.splitlines()[-1] and "wave check-in" in out.splitlines()[-1]


def test_recap_reaches_the_screen_through_bus_and_brain():
    import tempfile

    path, commands, _ = rehearse.demo_script()
    with tempfile.TemporaryDirectory() as folder:
        stack = rehearse.Stack(folder)
        stack.calibrate()
        stack.play(path, commands)
    recaps = {s["narration"]["text"] for s in stack.states if s["narration"]}
    assert len(recaps) == 1                                      # one recap, after the reset only
    text = recaps.pop()
    names = [rehearse.LAYOUT.names[z] for z in rehearse.TOUR]   # visited in tour order
    assert all(name.lower() in text.lower() for name in names) and text.startswith("Someone ")   # "on the left"
    assert "no-movement alert" in text and "dBm" in text


HERO = ["found:", "lesson:", "unplug:", "still:", "armed,", "intrusion while armed", "tamper:", "disarmed"]   # in order


@pytest.fixture(scope="module")
def desk():
    return rehearse.rehearse(rehearse.desk_script())


def test_the_desk_visit_plays_the_hero_path_in_order(desk):
    names = [name for name, _, _ in desk]
    first = [next(i for i, n in enumerate(names) if n.startswith(beat)) for beat in HERO]
    assert first == sorted(first), names
    path, commands, beats = rehearse.desk_script()
    # the lesson as the screen sends it: train while the lesson's recording is still open
    assert [c[1] for c in commands] == ["label_mode", "record_start", "train", "record_stop", "label_mode", "arm", "arm"]
    assert path["duration_s"] <= 180                                          # it fits the 3-minute visit


def test_every_desk_beat_shows_up(desk):
    failed = [name for name, passed, _ in desk if not passed]
    assert failed == [], failed


def test_desk_beats_show_in_good_time(desk):
    shown = {name: s for name, _, s in desk}
    assert shown["found: the judge steps up"] <= 2.0
    assert shown["lesson: a model within 5 s of train"] <= 5.0
    assert 10.0 <= shown["still: no-movement alert"] <= 13.0                  # the 10 s limit, then the smoothing
    assert 3.0 <= shown["intrusion while armed"] <= 5.0                       # steps back in, and is still there 3 s later


def test_nobody_stands_long_enough_to_alert_before_the_still_beat():
    """On the desk both zones alert after 10 s, so an early long stand would raise the alert too soon."""
    path, _, beats = rehearse.desk_script()
    still_from = next(b[1] for b in beats if b[0] == "still: no-movement alert")
    stops = [p for p in path["person"] if p.get("x") is not None and p["t"] <= still_from]
    stands = [b["t"] - a["t"] for a, b in zip(stops, stops[1:]) if (a["x"], a["y"]) == (b["x"], b["y"])]
    assert max(stands) <= 5


def test_a_command_lands_at_its_own_time(tmp_path):
    stack = rehearse.Stack(str(tmp_path))
    t0 = stack.play({"name": "empty", "duration_s": 3, "person": None}, [(2.0, "arm", {"on": True})])
    armed = [e for e in stack.events if e["kind"] == "armed"]
    assert len(armed) == 1 and 2.0 <= (armed[0]["t"] - t0) / 1000 < 2.2


def test_desk_flag_runs_the_desk_visit(capsys, monkeypatch):
    seen = []
    monkeypatch.setattr(rehearse, "rehearse", lambda script=None: seen.append(script) or [("a beat", True, 1.0)])
    assert rehearse.main(["--desk"]) == 0
    assert seen[0][0]["name"] == "desk" and "1 of 1 beats passed" in capsys.readouterr().out


def test_the_unplugged_beacon_raises_one_tamper_and_no_intrusion():
    import tempfile
    path, commands, _ = rehearse.desk_script()
    with tempfile.TemporaryDirectory() as folder:
        stack = rehearse.Stack(folder)
        stack.calibrate()
        t0 = stack.play(path, commands)
    unplug = path["outages"][0]["t_on"]
    late = [e["kind"] for e in stack.events if (e["t"] - t0) / 1000 >= unplug]
    assert late.count("tamper") == 1 and late.count("tamper_cleared") == 1 and "intrusion" not in late
    assert late.index("tamper_cleared") < late.index("disarmed")


def test_the_tamper_beats_show_in_good_time(desk):
    shown = {name: s for name, _, s in desk}
    assert 2.5 <= shown["tamper: a beacon unplugged while armed"] <= 4.0      # 3 s of silence from every east link
    assert shown["tamper: cleared when the beacon is back"] <= 3.0            # 2 s after its links are back
