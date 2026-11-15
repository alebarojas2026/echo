"""The live lesson: train on an open recording, keep fitting while the camera is on, score the
radio against the camera, and carry on when the camera goes (brain/lesson.py)."""
import pytest

from brain.core import Brain
from brain.lesson import LAST_N, REFIT_MS, Lesson
from brain.tests.test_core import Feed, cmd

META = {"session": "lesson1", "purpose": "train", "walker": "judge"}


def label(zone, t=0, clipped=False):
    return {"present": zone != 0, "zone": None if clipped else zone, "clipped": clipped, "recv_t": t}


def pred(zone):
    return {"present": zone != 0, "zone": zone}


# ---- the lesson's own rules ----

def test_no_lesson_without_an_open_train_recording():
    lesson = Lesson()
    lesson.train_cmd(1000, None)
    assert not lesson.on and lesson.block(None) is None
    assert lesson.block({"started_t": 1, "progress": None, "sessions": ["s1"]}) == \
        {"started_t": 1, "progress": None, "sessions": ["s1"]}
    assert not lesson.due(10**9, None, "on", False)


def test_fits_again_every_refit_while_the_camera_is_on():
    lesson = Lesson()
    lesson.train_cmd(1000, "s1")
    lesson.fitted(3000, True)
    assert lesson.on and lesson.fits == 1
    assert not lesson.due(3000 + REFIT_MS - 1, "s1", "on", False)
    assert lesson.due(3000 + REFIT_MS, "s1", "on", False)
    assert not lesson.due(3000 + REFIT_MS + 100, "s1", "on", False)   # asked once, not on every tick
    assert not lesson.due(3000 + 3 * REFIT_MS, "s1", "stalled", False)  # no labels to learn from just now
    assert not lesson.due(3000 + 3 * REFIT_MS, "s1", "on", True)        # a fit is still running
    lesson.fitted(60_000, False)                                        # a failed fit doesn't count
    assert lesson.fits == 1 and not lesson.due(60_000 + REFIT_MS - 1, "s1", "on", False)


@pytest.mark.parametrize("session, cam", [("s1", "off"), (None, "on")])
def test_one_last_fit_when_the_camera_goes_or_the_recording_stops(session, cam):
    lesson = Lesson()
    lesson.train_cmd(1000, "s1")
    lesson.fitted(2000, True)
    assert not lesson.due(2100, session, cam, True) and not lesson.on   # over, but a fit is running
    assert lesson.due(2200, session, cam, False)                        # the last fit, once it can start
    lesson.train_cmd(2200, "s1")                                        # that fit is not a new lesson,
    assert not lesson.on                                                # even with the recording still open
    assert not lesson.due(2300 + REFIT_MS, session, cam, False)
    assert lesson.block(None) is None


def test_agreement_counts_the_last_decisions_that_had_a_camera_label():
    lesson = Lesson()
    lesson.saw(0, pred(1), label(1))
    assert lesson.agreement() == (0, 0)             # no lesson, nothing counted
    lesson.train_cmd(1000, "s1")
    assert lesson.block(None)["lesson"] == {"started_t": 1000, "agree": 0, "of": 0, "fits": 0, "fitting": False}
    for radio, camera in [(1, 1), (2, 1), (0, 0), (1, 0), (2, 2)]:
        lesson.saw(2000, pred(radio), label(camera, 2000))
    lesson.saw(2000, pred(1), label(1, 2000, clipped=True))   # a dropped label says nothing
    lesson.saw(4000, pred(1), label(1, 2000))                 # nor does an old one
    lesson.saw(2000, None, label(1, 2000))                    # nor a hidden prediction
    lesson.saw(2000, pred(1), None)
    assert lesson.agreement() == (3, 5)
    for _ in range(LAST_N):
        lesson.saw(2000, pred(2), label(2, 2000))
    assert lesson.agreement() == (LAST_N, LAST_N)
    fitting = lesson.block({"started_t": 5000, "progress": None, "sessions": ["s0", "s1"]})
    assert fitting["sessions"] == ["s0", "s1"] and fitting["lesson"]["fitting"] is True
    assert lesson.block(None)["sessions"] == ["s1"]


# ---- through the brain ----

def started():
    """A baseline, an empty recording, then a lesson recording opened on the walker."""
    brain = Brain()
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    feed.record("s01", "empty_room", seed=2)
    brain.on_cmd(cmd("label_mode", mode="person"))
    brain.on_cmd(cmd("record_start", **META))
    return brain, feed


def kinds(brain):
    return [e["kind"] for e in brain.pop_events()]


def test_train_during_the_recording_starts_a_lesson_that_keeps_fitting_and_survives_the_camera():
    check = pytest.importorskip("contracts.check")
    brain, feed = started()
    kinds(brain)
    start = feed.t
    sent = []

    def train_at_20_s(m):
        if not sent and m["recv_t"] - start >= 20_000:
            sent.append(brain.on_cmd(cmd("train")))

    feed.play("zone_tour", seed=5, meta=META, each=train_at_20_s)
    assert "trained" in kinds(brain)
    s = brain.state()
    assert s["model"]["trained"] and s["model"]["train_sessions"] == ["lesson1", "s01"]
    assert brain.lesson.on and brain.lesson.fits == 1 and s["pred"] is not None
    first, first_windows = s["model"]["ver"], s["model"]["windows"]
    lesson = s["model"]["training"]["lesson"]
    assert lesson["of"] == LAST_N and 0 <= lesson["agree"] <= LAST_N and lesson["fitting"] is False
    assert s["model"]["training"]["sessions"] == ["lesson1"] and check.errors(s) == []

    states = []
    feed.play("zone_tour", seed=6, states=states)        # the recording is still open, the camera still on
    s = states[-1][1]
    assert brain.lesson.fits >= 2 and s["model"]["ver"] != first and s["model"]["windows"] > first_windows
    assert kinds(brain).count("trained") == brain.lesson.fits - 1
    agree = s["model"]["training"]["lesson"]["agree"]
    assert agree >= 7, f"the radio agreed with the camera on only {agree} of {LAST_N}"

    before_unplug, states = s["model"]["ver"], []
    feed.play("camera_unplug", seed=7, states=states)    # the camera goes at 14 s; nobody sends a command
    assert not brain.lesson.on
    after = [st for t, st in states if t > 18]
    assert all(st["cam"] == "off" and st["teacher"] is None and st["model"]["training"] is None for st in after)
    assert all(st["pred"] is not None for st in after)   # the radio carries on
    assert after[-1]["model"]["ver"] != before_unplug    # the one last fit
    final = after[-1]["model"]["ver"]
    feed.play("zone_tour", seed=8, states=states)
    assert states[-1][1]["model"]["ver"] == final        # and no more fits after it
    assert all(check.errors(st) == [] for _, st in states[::25])


def test_record_stop_ends_the_lesson_with_a_last_fit():
    brain, feed = started()
    feed.play("zone_tour", seed=5, meta=META)
    brain.on_cmd(cmd("train"))
    assert brain.lesson.on and brain.model_n == 1
    brain.on_cmd(cmd("record_stop"))
    s = brain.state()
    assert not brain.lesson.on and brain.model_n == 2 and s["model"]["training"] is None
    assert s["model"]["train_sessions"] == ["lesson1", "s01"]


def test_a_recording_that_is_stopped_before_train_is_not_a_lesson():
    brain, feed = started()
    feed.play("zone_tour", seed=5, meta=META)
    brain.on_cmd(cmd("record_stop"))
    brain.on_cmd(cmd("train"))
    states = []
    feed.play("zone_tour", seed=6, states=states)
    assert not brain.lesson.on and brain.model_n == 1
    assert all(st["model"]["training"] is None for _, st in states)


def test_the_fit_reads_the_bus_file_as_far_as_it_has_got(tmp_path):
    import json
    from brain.tests.simdata import sim_to_v2

    brain = Brain(sessions_dir=tmp_path)
    feed = Feed(brain)
    brain.on_cmd(cmd("baseline"))
    feed.play("empty_room", seed=1)
    brain.on_cmd(cmd("record_start", **META))
    msgs = sim_to_v2("zone_tour", seed=5, meta=META, t0=feed.t)
    with open(tmp_path / "lesson1.jsonl", "a") as f:     # the bus writes the file; the brain holds nothing
        for i, m in enumerate(msgs):
            f.write(json.dumps(m) + "\n")
            f.flush()
            brain.on_message(m)
            if i == len(msgs) * 2 // 3:
                assert brain.open_session["messages"] is None
                brain.on_cmd(cmd("train"))
                windows = brain.state()["model"]["windows"]
        f.write('{"v":2,"type":"rssi","recv_')            # a line the bus is still writing
        f.flush()
        brain.on_cmd(cmd("train"))
    assert 0 < windows < brain.state()["model"]["windows"] and brain.lesson.on
