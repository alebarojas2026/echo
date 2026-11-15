"""The desk view tells someone in the strip from someone standing back (teacher/DESK.md), so the
lesson never teaches the radio that links nobody is touching can mean a person."""
import json

import pytest

from contracts import check
from teacher import calibrate
from teacher.applab.python import preflight
from teacher.applab.python.labels import DeskView, Teacher
from teacher.calibrate import desk_config

SIZE = [640, 480]
STRIP = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}


def box(centre, width):
    return dict(label="person", value=0.9, x=centre - width / 2, y=40, width=width, height=440)


def teacher(sent, **config):
    return Teacher(DeskView({**desk_config(STRIP), **config}, SIZE), sent.append, clock=lambda: 1000)


def test_a_near_box_is_present_and_a_far_box_is_clipped_never_present():
    sent = []
    t = teacher(sent, near_width=0.25)
    near = t.processed([box(480, 200)])          # 0.31 of the frame: at the desk edge
    assert (near["present"], near["zone"], near["clipped"], near["persons_in_frame"]) == (True, 1, False, 1)
    far = t.processed([box(480, 110)])           # 0.17 of the frame: one step back
    assert (far["present"], far["clipped"], far["persons_in_frame"]) == (False, True, 1)
    assert (far["zone"], far["foot_m"], far["motion"], far["conf"]) == (None, None, None, 0.0)
    edge = t.processed([box(160, 160)])          # exactly on the threshold counts as in the strip
    assert edge["present"] is True and edge["zone"] == 2
    assert [check.errors(label) for label in sent] == [[]] * 3


def test_nobody_in_view_is_still_plain_nobody():
    sent = []
    label = teacher(sent, near_width=0.25).processed([])
    assert (label["present"], label["zone"], label["clipped"], label["persons_in_frame"]) == (False, 0, False, 0)


def test_without_a_threshold_nobody_is_labelled_present():
    sent = []
    t = teacher(sent)                            # desk_config alone: no near_width yet
    for width in (60, 200, 500):
        label = t.processed([box(400, width)])
        assert (label["present"], label["clipped"]) == (False, True)
    assert t.processed([])["clipped"] is False   # an empty view is still a good "nobody"


@pytest.mark.parametrize("bad", [0, 1.5, "0.3", True, -0.1])
def test_a_threshold_that_cannot_be_right_is_refused(bad):
    with pytest.raises(ValueError, match="near_width"):
        DeskView({**desk_config(STRIP), "near_width": bad}, SIZE)


def test_the_box_width_is_kept_for_the_calibration_and_only_for_one_person():
    t = teacher([], near_width=0.25)
    t.processed([box(480, 160)])
    assert t.box_w == 0.25
    t.processed([box(480, 160), box(100, 160)])
    assert t.box_w is None
    t.processed([])
    assert t.box_w is None


def test_preflight_says_plainly_when_the_threshold_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TEACHER_DESK_NEAR_WIDTH", raising=False)
    calib, mode = tmp_path / "calib.json", tmp_path / "label_mode"
    mode.write_text("off\n")
    args = ["preflight", "--calibration", str(calib), "--mode-file", str(mode),
            "--heartbeat", str(tmp_path / "heartbeat.json"), "--box-size", "640x480"]
    calib.write_text(json.dumps(desk_config(STRIP)))
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit) as stop:
        preflight.main()
    assert stop.value.code == 1 and "NOT READY FOR A LESSON" in capsys.readouterr().err
    assert preflight.check_files(calib, mode, tmp_path / "heartbeat.json", SIZE).near_width is None   # the app still starts
    calib.write_text(json.dumps({**desk_config(STRIP), "near_width": 0.25}))
    preflight.main()
    assert "are ready" in capsys.readouterr().out
    assert preflight.desk_view(desk_config(STRIP), SIZE, {"TEACHER_DESK_NEAR_WIDTH": "0.3"}).near_width == 0.3


# ---- the two-step calibration

class Beats:
    """A heartbeat file that gives the next width each time it is read."""

    def __init__(self, widths):
        self.widths, self.frame = list(widths), 0

    def __call__(self):
        self.frame += 1
        return {"t": self.frame, "frame": self.frame, "box_w": self.widths.pop(0) if self.widths else None}


def test_the_threshold_is_halfway_between_the_desk_edge_and_one_step_back(tmp_path):
    calib = tmp_path / "calib.json"
    calib.write_text(json.dumps(desk_config(STRIP)))
    asked, said = [], []
    read = Beats([0.40] * 8 + [0.20, 0.22, 0.21, None, 0.20, 0.20, 0.9, 0.20, 0.20])   # a missing frame and one outlier
    config = calibrate.calibrate_near(calib, read, ask=asked.append, clock=lambda: 0, sleep=lambda s: None, say=said.append)
    assert config["near_width"] == 0.3 and (config["near_edge_w"], config["near_back_w"]) == (0.4, 0.2)
    assert json.loads(calib.read_text())["near_width"] == 0.3
    assert asked[0].startswith("1 of 2.") and "desk edge" in asked[0] and asked[1].startswith("2 of 2.") and "one step back" in asked[1]
    assert DeskView(json.loads(calib.read_text()), SIZE).near(200) is True


@pytest.mark.parametrize("edge, back", [(0.30, 0.28), (0.2, 0.3), (0.3, 0.3)])
def test_two_boxes_too_alike_to_tell_apart_are_refused(edge, back):
    with pytest.raises(ValueError, match="bigger step back"):
        calibrate.near_width(edge, back)


def test_no_box_from_the_teacher_gives_up_with_a_plain_message(tmp_path):
    now = [0.0]

    def sleep(s):
        now[0] += 1
    with pytest.raises(ValueError, match="is the app running"):
        calibrate.box_width(lambda: None, lambda: now[0], sleep)
    with pytest.raises(ValueError, match="is the app running"):   # the same frame again and again is not fresh
        calibrate.box_width(lambda: {"t": 1, "frame": 1, "box_w": 0.3}, lambda: now[0], sleep)


def test_a_floor_view_file_is_refused(tmp_path):
    calib = tmp_path / "calib.json"
    calib.write_text(json.dumps({"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "image_size": [640, 480]}))
    with pytest.raises(ValueError, match="not a desk view file"):
        calibrate.calibrate_near(calib, lambda: None, ask=lambda q: None)
