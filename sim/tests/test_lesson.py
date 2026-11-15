"""The live lesson in the fake feed, the fake brain and the rehearsal (sim/lesson.py)."""
import json

import pytest

from contracts.check import check_lines
from sim import fake, lesson, rehearse, state
from sim.layout import Layout
from sim.wire import encoder

STRIP = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}, "nodes": [], "links": [],
         "zones": [{"id": 1, "name": "Left", "centre_m": [0.4, 0.3], "still_alert_s": 10},
                   {"id": 2, "name": "Right", "centre_m": [1.2, 0.3], "still_alert_s": 10}]}


def test_left_and_right_come_from_the_layout():
    assert [zone for zone, _ in lesson.sides()] == [1, 2]
    assert lesson.sides(Layout(STRIP)) == ((1, (0.4, 0.3)), (2, (1.2, 0.3)))
    strip = lesson.path(Layout(STRIP))
    assert {(w["x"], w["y"]) for w in strip["person"] if w["x"] is not None} == {(0.4, 0.3), (1.2, 0.3)}


def test_the_path_is_the_lesson_then_the_unplug():
    path = fake.load_path("lesson")
    assert path == lesson.path() and path["name"] == "lesson"
    times = [w["t"] for w in path["person"]]
    assert times == sorted(times) and times[-1] <= path["duration_s"]
    assert lesson.RECORD_S < lesson.TRAIN_S < lesson.CAM_OFF_S < lesson.STOP_S < lesson.END_S
    assert lesson.TRAIN_S - lesson.RECORD_S == 20
    both = {zone for start, end, zone in lesson.stands() if lesson.RECORD_S <= start and end <= lesson.TRAIN_S}
    assert both == {1, 2}                                   # both sides are taught before train
    after = {zone for start, _, zone in lesson.stands() if start >= lesson.CAM_OFF_S + 3}
    assert after == {1, 2}                                  # and both are visited with the camera gone


def test_the_feed_has_desk_labels_until_the_camera_goes():
    events = list(fake.simulate(lesson.path()))
    labels = [e for e in events if e["type"] == "label"]
    assert labels and all(e["foot_m"] is None for e in labels)          # the desk view has no foot point
    assert {e["zone"] for e in labels} == {0, 1, 2, None}
    crossing = [e for e in labels if e["clipped"]]
    assert crossing and all(e["present"] and e["zone"] is None and e["motion"] is None for e in crossing)
    assert max(e["t"] for e in labels) < lesson.CAM_OFF_S
    assert [e["state"] for e in events if e["type"] == "cam" and e["t"] >= lesson.CAM_OFF_S][0] == "off"
    assert max(e["t"] for e in events if e["type"] == "rssi") > lesson.END_S - 1   # the radio carries on
    encode = encoder(1_763_149_500_000)
    assert check_lines(encode(e) for e in events)[1] == []


def test_other_paths_keep_their_foot_points():
    labels = [e for e in fake.simulate(fake.load_path("zone_tour")) if e["type"] == "label" and e["present"]]
    assert labels and all(e["foot_m"] is not None and not e["clipped"] for e in labels)


@pytest.fixture(scope="module")
def played():
    return list(state.run(lesson.path()))


def at(played, t):
    return next(m for m in played if m["type"] == "state" and m["t"] >= t)


def test_the_fake_brain_shows_learning_then_carries_on_without_the_camera(played):
    assert at(played, lesson.TRAIN_S - 1)["model"]["training"] is None        # recording, not yet a lesson
    first = at(played, lesson.TRAIN_S + 0.5)["model"]["training"]
    assert first["lesson"] == {"started_t": 25_000, "agree": 5, "of": 5, "fits": 1, "fitting": False}
    assert first["sessions"] == [lesson.SESSION] and first["progress"] is None
    seen = [at(played, t)["model"]["training"]["lesson"] for t in (lesson.TRAIN_S + 2, lesson.TRAIN_S + 16, lesson.CAM_OFF_S - 1)]
    assert [(s["agree"], s["of"], s["fits"]) for s in seen] == [(6, 10, 1), (8, 10, 2), (8, 10, 2)]
    gone = at(played, lesson.CAM_OFF_S + 1)
    assert gone["cam"] == "off" and gone["teacher"] is None and gone["model"]["training"] is None
    for start, end, zone in lesson.stands():
        if start > lesson.CAM_OFF_S:
            s = at(played, start + 1)
            assert s["pred"]["present"] and s["pred"]["zone"] == zone and s["model"]["trained"]


def test_the_fake_brain_says_trained_at_every_fit(played):
    fits = [m["t"] for m in played if m["type"] == "event" and m["kind"] == "trained"]
    assert fits == [state.TRAINED_AT_S, lesson.TRAIN_S, lesson.TRAIN_S + lesson.REFIT_S, lesson.CAM_OFF_S]
    assert lesson.fit_times({"train_at": 10, "refit_s": 15, "stop_at": 30}, cam_off=50) == [10, 25, 30]


def test_the_fake_brain_passes_the_contract(played):
    encode = encoder(1_763_149_500_000)
    count, failures, _ = check_lines(encode(m) for m in played)
    assert count == len(played) and failures == []
    assert json.loads(encode(at(played, 30)))["model"]["training"]["lesson"]["of"] == 10


def test_a_path_without_a_lesson_never_has_a_training_block():
    assert all(m["model"]["training"] is None for m in state.run(fake.load_path("camera_unplug")) if m["type"] == "state")


# ---- the rehearsal: the real bus and the real brain ----

@pytest.fixture(scope="module")
def results():
    return rehearse.rehearse(lesson=True)


def test_teach_then_unplug_passes(results):
    names = [name for name, _, _ in results]
    assert names[:2] == ["setup: baseline", "setup: no model yet"]
    assert any(name.startswith("teach, then unplug: the radio follows left and right") for name in names)
    assert [name for name, passed, _ in results if not passed] == []


def test_the_first_model_comes_within_seconds_of_train(results):
    shown = {name: s for name, _, s in results}
    assert shown["lesson: a model within 5 s of train"] <= 1      # sim time: the fit is instant on the feed's clock


def test_without_the_train_command_the_lesson_beats_fail_by_name():
    path, commands, beats = rehearse.lesson_script()
    results = rehearse.rehearse((path, [c for c in commands if c[1] != "train"], beats), lesson=True)
    failed = {name.split(" (")[0] for name, passed, _ in results if not passed}
    assert {"lesson: a model within 5 s of train", "lesson: the learning signal counts 10 decisions",
            "teach, then unplug: radio only", "teach, then unplug: the radio follows left and right"} <= failed
