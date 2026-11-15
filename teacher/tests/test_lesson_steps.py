"""The guided lesson's steps and its empty-time rule (teacher/lesson.py)."""
from teacher.lesson import EMPTY, LEFT, MOVE, NO_EMPTY, RIGHT, STILL, EmptyTime, no_empty, script

SEEN, NOBODY, DROPPED = {"present": True, "zone": 1}, {"present": False, "zone": 0}, None


def test_the_lesson_starts_empty_and_steps_out_once_in_the_middle():
    steps = script(30, 4)
    assert [(t, what) for t, what, _ in steps] == [(0.0, EMPTY), (6, LEFT), (10, RIGHT), (14, EMPTY), (19, LEFT),
                                                   (23, RIGHT), (27, LEFT)]
    assert "Stay out of the camera's view" in steps[0][2] and "Step right out of the camera's view" in steps[3][2]
    assert "Step in on your LEFT" in steps[1][2] and "Step in on your LEFT" in steps[4][2]   # coming back in


def test_a_short_lesson_still_starts_empty():
    steps = script(12, 4)
    assert steps[0][1] == EMPTY and {what for _, what, _ in steps[1:]} == {LEFT, RIGHT}
    assert all(t < 12 for t, _, _ in steps)


def test_empty_time_needs_three_seconds_of_the_camera_seeing_nobody():
    e = EmptyTime()
    for s in range(0, 3):
        e.saw(s, "on", NOBODY)
    assert not e.ok()
    e.saw(3, "on", NOBODY)
    assert e.ok() and e.stretches == 1
    e.saw(4, "on", NOBODY)
    assert e.stretches == 1                       # one long stretch is counted once
    e.saw(5, "on", SEEN)
    for s in range(6, 10):
        e.saw(s, "on", NOBODY)
    assert e.stretches == 2 and "2 stretches" in e.summary()


def test_standing_back_a_broken_stretch_and_a_camera_that_is_off_are_not_empty():
    e = EmptyTime()
    for s in range(0, 10):
        e.saw(s, "on", DROPPED)                   # someone standing back: the label was dropped
    for s in range(10, 20):
        e.saw(s, "off", NOBODY)
    for s in range(20, 30):
        e.saw(s, "on", NOBODY if s % 3 else SEEN)   # never 3 s in a row
    assert not e.ok() and "none" in e.summary()


SIDES = ("left", "right", "LEFT", "RIGHT", "Left", "Right")


def test_on_one_spot_the_lesson_is_empty_still_moving_off_and_back_on_with_no_side():
    steps = script(30, 4, one_zone=True)
    assert [(t, what) for t, what, _ in steps] == [(0.0, EMPTY), (10, STILL), (14, MOVE), (18, EMPTY), (23, STILL),
                                                   (27, MOVE)]
    words = [w for _, _, w in steps]
    assert words[0].startswith("Stay off the spot and out of the camera's view")   # about 10 s empty
    assert words[1] == "Step onto the spot and stand still."
    assert words[2] == "Stay on the spot: shift your weight and move your arms."
    assert words[3] == "Step off the spot, out of the camera's view, for 5 seconds."   # 18 to 23 s
    assert words[4] == "Step back onto the spot and stand still."
    assert not any(side in w for w in words for side in SIDES)


def test_a_short_lesson_on_one_spot_still_starts_empty_and_names_no_side():
    steps = script(12, 4, one_zone=True)
    assert steps[0][1] == EMPTY and {what for _, what, _ in steps[1:]} == {STILL, MOVE}
    assert all(t < 12 for t, _, _ in steps)
    assert not any(side in w for _, _, w in steps for side in SIDES)


def test_two_zones_keep_their_left_and_right_words():
    assert script(30, 4, one_zone=False) == script(30, 4)
    assert "Step in on your LEFT and stand there." in [w for _, _, w in script(30, 4)]


def test_the_no_empty_words_name_no_side_on_one_spot():
    assert no_empty(False) == NO_EMPTY and "right out" in NO_EMPTY
    assert not any(side in no_empty(True) for side in SIDES) and "Step off the spot" in no_empty(True)
