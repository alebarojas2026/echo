"""The people rules' numbers are settings read from one place (brain/settings.py), and a
recording can be played through the real brain to count what a setting changes (brain/replay.py)."""
import json
import os

import pytest

from brain import features as F
from brain import replay as R
from brain import settings as S
from brain import train as T
from brain.alert import Armed, Watch
from brain.core import Brain
from brain.tests.simdata import sim_to_v2
from brain.tests.test_core import Feed, taught_on_disk
from brain.tests.test_train import session

PERSON = {"present": True, "kind": "person", "zone": 4, "zone_set": [4], "motion": "still"}
MOVING = dict(PERSON, motion="moving")
NOBODY = {"present": False, "kind": "none", "zone": 0, "zone_set": [], "motion": None}


def test_the_defaults_are_the_contract_values():
    assert S.DEFAULT.as_dict() == {
        "smooth_decisions": 10, "smooth_majority": 6,          # section 6, Alert: the majority of the last 10
        "moving_run": 5,                                       # ... 5 moving decisions in a row (0.5 s)
        "intrusion_decisions": 10, "intrusion_majority": 6,    # section 6, Armed: the majority of the last 10
        "zone_hold": 5, "motion_links": None}
    assert Brain().settings == S.DEFAULT


def test_a_wrong_name_or_value_is_an_error_not_a_silent_default(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="not a setting: moving_runs"):
        S.DEFAULT.with_(moving_runs=8)
    for bad in ({"moving_run": 0}, {"moving_run": 2.5}, {"moving_run": True}, {"smooth_majority": 5},
                {"intrusion_majority": 11}, {"motion_links": "east>unoq:ble"}, {"motion_links": []}):
        with pytest.raises(ValueError):
            S.DEFAULT.with_(**bad)
    file = tmp_path / "settings.json"
    file.write_text(json.dumps({"moving_run": 8, "motion_links": ["east>unoq:ble"]}))
    assert S.load(file) == S.DEFAULT.with_(moving_run=8, motion_links=("east>unoq:ble",))
    monkeypatch.setenv("RADIO_SIGHT_SETTINGS", str(file))
    assert Brain().settings.moving_run == 8 and Brain().watch.settings.moving_run == 8
    file.write_text(json.dumps({"moving_runs": 8}))
    with pytest.raises(ValueError):
        Brain()


def raised(rule, preds):
    return [z for z in (rule.on_pred(p) for p in preds) if z is not None]


def test_the_intrusion_hold_is_a_setting():
    crossing = [NOBODY] * 20 + [PERSON] * 15 + [NOBODY] * 20           # somebody crosses in 1.5 s
    today = Armed()
    today.arm(True)
    assert raised(today, crossing) == [4]                               # today's rule: 6 of the last 10
    longer = Armed(S.DEFAULT.with_(intrusion_decisions=30, intrusion_majority=20))   # 2 of the last 3 s
    longer.arm(True)
    assert raised(longer, crossing) == []
    assert raised(longer, [PERSON] * 19) == [] and raised(longer, [PERSON]) == [4]   # the 20th decision


def still_after(watch, preds):
    t = 1_000_000
    for p in preds:
        t += 100
        watch.on_pred(t, p)
    return watch.still_ms


def test_the_still_timer_reset_count_is_a_setting_and_resets_are_counted():
    stand = [PERSON] * 30 + [MOVING] * 6 + [PERSON] * 10                # 0.6 s of "moving" in a 4.6 s stand
    today = Watch({4: 10})
    assert still_after(today, stand) == 1000 and today.resets == {"moving": 1, "zone": 0, "gone": 0}
    patient = Watch({4: 10}, settings=S.DEFAULT.with_(moving_run=10))
    assert still_after(patient, stand) > 4000 and patient.resets["moving"] == 0
    assert still_after(today, [NOBODY] * 10) == 0 and today.resets["gone"] == 1     # walking out is counted apart


def test_the_arrival_hold_is_a_setting():
    for hold in (5, 8):
        brain = Brain(settings=S.DEFAULT.with_(zone_hold=hold))
        for _ in range(hold - 1):
            brain._announce(2)
        assert brain.pop_events() == []
        brain._announce(2)
        assert [(e["kind"], e["info"]) for e in brain.pop_events()] == [("enter", {"zone": 2})]


def test_motion_links_picks_the_links_that_decide_moving_or_still():
    base = F.baseline(sim_to_v2("empty_room", seed=99))
    sessions = [session("s01", "empty_room", seed=10), session("t0", "zone_tour", walker="w1", seed=20),
                session("st0", "stand_still", walker="w1", seed=30)]
    every = T.Model(base).fit(sessions)
    two = T.Model(base, motion_links=("east>pi5:ble", "east>unoq:ble")).fit(sessions)
    n = len(F.STATS)
    assert every.motion.n_features_in_ == len(F.LINKS) * n and two.motion.n_features_in_ == 2 * n
    assert two.zone.n_features_in_ == len(F.LINKS) * n                  # zone and kind still use every link
    window = list(F.windows(sessions[2]["messages"], base))[60]
    assert two.predict(window)["motion"] in ("moving", "still") and every.predict(window)["motion"] in ("moving", "still")
    del every.motion_links                                              # a model file from before the setting
    assert every.predict(window)["motion"] in ("moving", "still")
    with pytest.raises(ValueError, match="doesn't have"):
        T.Model(base, motion_links=("north>unoq:ble",))


def write_recording(folder, name, path, seed, t0):
    msgs = sim_to_v2(path, seed=seed, t0=t0, meta={"session": name, "purpose": "crowd", "walker": "x"})
    with open(folder / f"{name}.jsonl", "w") as f:
        for m in msgs:
            f.write(json.dumps(m) + "\n")
    return msgs[-1]["recv_t"] + 100


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    """A taught brain's folder (baseline.json, model.pkl, the recordings), plus two recordings to
    play back: a stand in the alert zone, and three people walking past, 2 s in the square each."""
    folder = tmp_path_factory.mktemp("sessions")
    brain, feed = taught_on_disk(folder)
    feed.t = write_recording(folder, "stand", "stand_still", 5, feed.t)
    person = []
    for start in (5, 15, 25):
        person += [{"t": start, "x": 0.0, "y": 0.5}, {"t": start + 2, "x": 2.0, "y": 0.5}, {"t": start + 2.1, "x": None}]
    passers = folder / "passers.path"
    passers.write_text(json.dumps({"name": "passers", "duration_s": 35, "person": [{"t": 0, "x": None}] + person}))
    write_recording(folder, "passers", str(passers), 6, feed.t)
    passers.unlink()
    return folder


def run(folder, tmp_path, name, armed=False, train=None, **changes):
    brain = R.prepared(folder, S.DEFAULT.with_(**changes), train, tmp_path)
    return R.replay(brain, R.read_session(folder / f"{name}.jsonl"), armed=armed)


def test_a_recording_played_through_the_real_brain_counts_intrusions_alerts_and_resets(recorded, tmp_path):
    before = {p.name: p.stat().st_mtime_ns for p in recorded.iterdir()}
    stand = run(recorded, tmp_path, "stand")
    assert stand["alerts"] == 1 and stand["intrusions"] == 0 and stand["longest_still_s"] >= 10
    assert 19 <= stand["seconds"] <= 20 and stand["states"] >= 190 and stand["present_s"] >= 14
    assert stand["settings"] == S.DEFAULT.as_dict()
    passers = run(recorded, tmp_path, "passers", armed=True)
    assert passers["intrusions"] == 3 and passers["alerts"] == 0        # today's rule: every passer-by is an intrusion
    assert {p.name: p.stat().st_mtime_ns for p in recorded.iterdir()} == before     # the folder is only read


def test_a_setting_changes_the_count_on_the_same_recording(recorded, tmp_path):
    held = run(recorded, tmp_path, "passers", armed=True, intrusion_decisions=40, intrusion_majority=30)
    assert held["intrusions"] == 0 and held["settings"]["intrusion_majority"] == 30
    assert run(recorded, tmp_path, "passers")["intrusions"] == 0        # not armed: nothing to raise


def test_the_command_prints_the_counts_and_can_fit_its_own_model(recorded, capsys):
    R.main([str(recorded / "passers.jsonl"), "--sessions", str(recorded), "--armed", "--set", "moving_run=8"])
    out = json.loads(capsys.readouterr().out)
    assert out["intrusions"] == 3 and out["settings"]["moving_run"] == 8 and out["armed"] is True
    assert out["recording"] == {"file": "passers.jsonl", "src": "sim", "purpose": "crowd"}
    R.main([str(recorded / "stand.jsonl"), "--sessions", str(recorded), "--train", "s01", "s10", "s11",
            "--set", "motion_links=east>pi5:ble,east>unoq:ble"])
    out = json.loads(capsys.readouterr().out)
    assert out["settings"]["motion_links"] == ["east>pi5:ble", "east>unoq:ble"] and out["present_s"] >= 14
    with pytest.raises(SystemExit, match="not a setting"):
        R.main([str(recorded / "stand.jsonl"), "--sessions", str(recorded), "--set", "moving_runs=8"])
    assert not os.environ.get("RADIO_SIGHT_SETTINGS")
