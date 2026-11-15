"""The desk view: left / right / nobody from the person box alone (teacher/DESK.md)."""
import json

import pytest

from teacher.applab.python.labels import DeskView, Teacher
from teacher.applab.python.preflight import check_files, desk_view, validate
from teacher.calibrate import desk_config

SIZE = [640, 480]
STRIP = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}
SQUARE = {"frame": {"size_m": [2.0, 2.0]}}


def box(centre, width=160, y=40, height=440, value=0.9):
    """A torso: it runs off the bottom of the frame, as it does from a desk."""
    return dict(label="person", value=value, x=centre - width / 2, y=y, width=width, height=height)


def teacher(sent=None, clock=None, **config):
    view = DeskView({**desk_config(STRIP), **config}, SIZE)
    return Teacher(view, (sent if sent is not None else []).append, clock=clock or (lambda: 1000))


def test_config_comes_from_the_layout():
    config = desk_config(STRIP)
    assert config["view"] == "desk" and config["zones"] == [1, 2]
    assert config["split"] == 0.5 and config["mirror"] is True and config["view_m"] == 1.6
    json.dumps(config, allow_nan=False)   # numbers and words only


def test_camera_off_the_split_line_moves_the_split():
    # The camera sits 0.4 m east of the line and faces the person: west is on the right of its
    # frame, so the line is right of centre.
    assert desk_config(STRIP, cam_x_m=1.2)["split"] == 0.75
    assert desk_config(STRIP, cam_x_m=1.2, mirror=False)["split"] == 0.25
    assert desk_config(STRIP, cam_x_m=1.0, view_m=0.8)["split"] == 0.75


@pytest.mark.parametrize("bad", [dict(cam_x_m=2.0), dict(view_m=0), dict(cam_x_m=1.6, view_m=1.0),
                                 dict(dead_band=0.6), dict(side_edge="drop")])
def test_config_that_cannot_work_is_refused(bad):
    with pytest.raises(ValueError):
        desk_config(STRIP, **bad)


def test_the_square_has_no_left_and_right():
    with pytest.raises(ValueError, match="two-zone strip"):
        desk_config(SQUARE)


def test_left_right_and_nobody_facing_the_person():
    t = teacher()
    # The camera faces the person: their left (zone 1, low x) is on the right of the frame.
    left, right, nobody = t.processed([box(480)]), t.processed([box(160)]), t.processed([])
    assert (left["zone"], right["zone"], nobody["zone"]) == (1, 2, 0)
    assert left["present"] and right["present"] and not nobody["present"]
    assert left["foot_m"] is None and left["motion"] == "still" and not left["clipped"]
    assert nobody["persons_in_frame"] == 0 and nobody["motion"] is None and nobody["conf"] == 0.0
    assert left["conf"] == 0.9 and left["persons_in_frame"] == 1


def test_not_mirrored_flips_the_sides():
    t = teacher(mirror=False)
    assert t.processed([box(480)])["zone"] == 2 and t.processed([box(160)])["zone"] == 1


def test_dead_band_around_the_split_is_dropped():
    t = teacher(dead_band=0.1)
    for centre in (320, 290, 350):
        label = t.processed([box(centre)])
        assert label["clipped"] and label["zone"] is None and label["motion"] is None and label["present"]
    assert t.processed([box(390)])["zone"] == 1 and t.processed([box(250)])["zone"] == 2


def test_cut_by_a_side_edge_is_dropped_but_a_torso_is_not():
    t = teacher()
    assert t.processed([box(80)])["clipped"] and t.processed([box(560)])["clipped"]
    whole_height = t.processed([box(480, y=0, height=480)])
    assert not whole_height["clipped"] and whole_height["zone"] == 1
    keep = teacher(side_edge="keep")
    assert keep.processed([box(80)])["zone"] == 2 and keep.processed([box(560)])["zone"] == 1


def test_more_than_one_person_is_dropped_and_weak_boxes_are_ignored():
    t = teacher()
    two = t.processed([box(160), box(480)])
    assert two["clipped"] and two["zone"] is None and two["persons_in_frame"] == 2 and two["present"]
    assert t.processed([box(160), box(480, value=0.2)])["zone"] == 2


def test_motion_follows_the_box_along_the_strip():
    now = [0]
    t = teacher(clock=lambda: now[0], dead_band=0.0)
    for i in range(21):     # 0.4 of a 1.6 m view in 2 s: 0.32 m/s
        now[0] = i * 100
        label = t.processed([box(200 + i * 12.8)])
    assert label["motion"] == "moving"
    for i in range(21):
        now[0] += 100
        label = t.processed([box(456)])
    assert label["motion"] == "still"


def test_every_desk_label_passes_the_contract():
    check = pytest.importorskip("contracts.check")
    sent = []
    t = teacher(sent)
    for boxes in ([], [box(480)], [box(160)], [box(320)], [box(80)], [box(160), box(480)]):
        t.processed(boxes)
    assert len(sent) == 6
    assert [check.errors(label) for label in sent] == [[]] * 6


def test_environment_overrides_the_file():
    config = desk_config(STRIP)
    view = desk_view(config, SIZE, {"TEACHER_DESK_MIRROR": "0", "TEACHER_DESK_SPLIT": "0.4",
                                    "TEACHER_DESK_DEAD_BAND": "0.02", "TEACHER_DESK_SIDE_EDGE": "keep"})
    assert (view.mirror, view.split, view.dead_band, view.side_edge) == (False, 0.4, 0.02, "keep")
    assert desk_view(config, SIZE, {}).mirror is True
    for bad in ({"TEACHER_DESK_MIRROR": "yes"}, {"TEACHER_DESK_SPLIT": "half"}, {"TEACHER_DESK_SPLIT": "1.5"}):
        with pytest.raises(ValueError):
            desk_view(config, SIZE, bad)


def test_preflight_takes_a_desk_file_and_refuses_a_broken_one(tmp_path, monkeypatch):
    for name in ("TEACHER_DESK_SPLIT", "TEACHER_DESK_DEAD_BAND", "TEACHER_DESK_MIRROR", "TEACHER_DESK_SIDE_EDGE"):
        monkeypatch.delenv(name, raising=False)
    calib, mode = tmp_path / "calib.json", tmp_path / "label_mode"
    mode.write_text("off\n")
    calib.write_text(json.dumps(desk_config(STRIP)))
    view = check_files(calib, mode, tmp_path / "heartbeat.json", SIZE)
    assert isinstance(view, DeskView) and (view.width, view.height) == (640, 480)
    assert isinstance(validate(desk_config(STRIP), SIZE), DeskView)
    calib.write_text(json.dumps({**desk_config(STRIP), "zones": [1, 1]}))
    with pytest.raises(ValueError, match="preflight failed"):
        check_files(calib, mode, tmp_path / "heartbeat.json", SIZE)
