"""Desk mode: a webcam on the desk tells left from right by the centre of the person box."""
import json

import pytest

from contracts.check import errors
from teacher.applab.python.labels import DeskView, Teacher
from teacher.applab.python.preflight import validate
from teacher.calibrate import desk_calibration

STRIP = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}


def view(**over):
    return DeskView({**desk_calibration([640, 480], 330, [40, 600], 2, STRIP), **over})


def box(u, w=120, top=20, h=400, conf=0.9):
    return {"label": "person", "value": conf, "x": u - w / 2, "y": top, "width": w, "height": h}


def run(boxes_per_frame, start=0, step_ms=100):
    sent, clock = [], [start]
    teacher = Teacher(view(), sent.append, clock=lambda: clock[0])
    for boxes in boxes_per_frame:
        teacher.processed(boxes)
        clock[0] += step_ms
    return sent


def test_left_right_and_nobody():
    # The camera looks out at the aisle, so the image's left is the east end: zone 2.
    left, right, nobody = run([[box(150)]])[0], run([[box(500)]])[0], run([[]])[0]
    assert (left["zone"], right["zone"], nobody["zone"]) == (2, 1, 0)
    assert left["present"] and left["foot_m"] is None and left["motion"] == "still"   # no floor point is sent
    assert nobody["present"] is False and nobody["foot_m"] is None and nobody["motion"] is None


def test_off_the_strip_and_clipped_at_the_sides():
    off = run([[box(20, w=20)]])[0]                    # centre left of u_min: someone beyond the strip's end
    assert off["present"] is False and off["zone"] == 0 and off["persons_in_frame"] == 1
    cut = run([[box(55, w=120)]])[0]                   # touches the image's left side
    assert cut["clipped"] is True and cut["zone"] is None
    tall = run([[box(300, top=0, h=480)]])[0]          # a close person fills the height: not clipped
    assert tall["clipped"] is False and tall["zone"] == 2


def test_walking_across_is_moving_standing_is_still():
    walk = run([[box(100 + 25 * i)] for i in range(20)])    # about 2 m/s across the image
    stand = run([[box(450)] for _ in range(20)])
    assert walk[-1]["motion"] == "moving" and stand[-1]["motion"] == "still"
    assert [m["zone"] for m in walk][0] == 2 and walk[-1]["zone"] == 1


def test_desk_labels_pass_the_contract_and_preflight():
    config = desk_calibration([640, 480], 330, [40, 600], 2, STRIP)
    assert isinstance(validate(json.loads(json.dumps(config)), [640, 480]), DeskView)
    for label in run([[box(150)], [box(500)], [], [box(20, w=20)], [box(55)]]):
        assert errors(label) == [], label


def test_bad_desk_configs_are_refused():
    with pytest.raises(ValueError):
        desk_calibration([640, 480], 330, [40, 600], 2, {"frame": {"size_m": [2.0, 2.0]}})   # the square: no strip
    with pytest.raises(ValueError):
        desk_calibration([640, 480], 700, [40, 600], 2, STRIP)                              # split outside the range
    with pytest.raises(ValueError):
        validate(desk_calibration([640, 480], 330, [40, 600], 2, STRIP), [1280, 720])       # another detector frame
