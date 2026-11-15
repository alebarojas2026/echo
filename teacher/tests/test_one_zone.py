"""A layout with one zone (one spot): the teacher says somebody or nobody, never a side.

The layout is teacher/fixtures/gate-nodes.json: a 0.8 x 0.6 m spot, no split line, one zone,
three devices, one of them outside frame.size_m.
"""
import json
import logging
from pathlib import Path

import pytest

from contracts.check import errors
from teacher.applab.python.labels import DeskView, Projection, Teacher, area_of, zone_in
from teacher.applab.python.preflight import area_size, check_files, desk_view, validate
from teacher.calibrate import area_from_nodes, area_text, calibrate_near, calibration, desk_config, foot_point

GATE = json.loads((Path(__file__).parents[1] / "fixtures/gate-nodes.json").read_text(encoding="utf-8"))
STRIP = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}
SIZE = [640, 480]


def box(centre, width=200):
    return dict(label="person", value=0.9, x=centre - width / 2, y=40, width=width, height=440)


def teacher(sent=None, clock=None, **config):
    view = DeskView({**desk_config(GATE), "near_width": 0.25, **config}, SIZE)
    return Teacher(view, (sent if sent is not None else []).append, clock=clock or (lambda: 1000))


def test_the_file_has_one_zone_and_no_line():
    assert len(GATE["zones"]) == 1 and "zone_split_x_m" not in GATE["frame"]
    assert area_from_nodes(GATE) == ([0.8, 0.6], [None, None])
    assert area_text(area_from_nodes(GATE)[0]) == "0.8x0.6"


def test_the_desk_file_has_no_split_and_no_dead_band():
    config = desk_config(GATE)
    assert config == {"view": "desk", "mirror": True, "side_edge": "clipped", "view_m": 0.8, "zones": [1]}
    json.dumps(config, allow_nan=False)
    assert desk_config(GATE, dead_band=0.3) == config          # the two-zone option means nothing here
    assert desk_config(GATE, view_m=1.2, mirror=False, side_edge="keep")["view_m"] == 1.2


@pytest.mark.parametrize("bad", [dict(cam_x_m=2.0), dict(view_m=0), dict(side_edge="drop")])
def test_a_desk_file_that_cannot_work_is_refused(bad):
    with pytest.raises(ValueError):
        desk_config(GATE, **bad)


def test_a_strip_with_no_line_needs_exactly_one_zone():
    two = {"frame": {"strip_m": [0.8, 0.6]}, "zones": [{"id": 1}, {"id": 2}]}
    with pytest.raises(ValueError, match="exactly one zone"):
        area_from_nodes(two)
    with pytest.raises(ValueError, match="one zone has no split"):
        DeskView({**desk_config(GATE), "split": 0.5}, SIZE)
    with pytest.raises(ValueError, match="desk view"):
        DeskView({**desk_config(GATE), "zones": []}, SIZE)
    with pytest.raises(ValueError, match="zones"):
        DeskView({**desk_config(GATE), "zones": [0]}, SIZE)


def test_anywhere_across_the_frame_is_the_one_zone():
    sent = []
    t = teacher(sent)
    for centre in (130, 300, 320, 340, 510):     # either side, and right on the middle of the frame
        label = t.processed([box(centre)])
        assert (label["present"], label["zone"], label["clipped"]) == (True, 1, False), centre
        assert label["foot_m"] is None and label["motion"] == "still" and label["persons_in_frame"] == 1
    nobody = t.processed([])
    assert (nobody["present"], nobody["zone"], nobody["clipped"], nobody["motion"]) == (False, 0, False, None)
    assert [errors(label) for label in sent] == [[]] * 6


def test_mirroring_changes_nothing_about_who_is_there():
    for mirror in (True, False):
        t = teacher(mirror=mirror)
        assert [t.processed([box(c)])["zone"] for c in (150, 490)] == [1, 1]


def test_standing_back_is_not_present_as_before():
    sent = []
    t = teacher(sent)
    far = t.processed([box(320, 110)])           # 0.17 of the frame: one step back
    assert (far["present"], far["clipped"], far["zone"], far["persons_in_frame"]) == (False, True, None, 1)
    edge = t.processed([box(320, 160)])          # exactly on the threshold counts as on the spot
    assert (edge["present"], edge["zone"], edge["clipped"]) == (True, 1, False)
    assert [errors(label) for label in sent] == [[], []]
    unmeasured = Teacher(DeskView(desk_config(GATE), SIZE), [].append, clock=lambda: 1000)
    assert (unmeasured.processed([box(320, 400)])["present"], unmeasured.processed([])["clipped"]) == (False, False)


def test_only_a_side_edge_or_a_second_person_clips():
    t = teacher()
    cut = t.processed([box(90)])                 # runs off the left edge of the frame
    assert (cut["present"], cut["zone"], cut["clipped"]) == (True, None, True)
    two = t.processed([box(200), box(450)])
    assert (two["present"], two["zone"], two["clipped"], two["persons_in_frame"]) == (True, None, True, 2)
    kept = teacher(side_edge="keep").processed([box(90)])
    assert (kept["zone"], kept["clipped"]) == (1, False)
    for label in (cut, two, kept):
        assert errors(label) == []


def test_moving_follows_the_box_along_the_spot():
    now = [0]
    t = teacher(clock=lambda: now[0])
    still = []
    for _ in range(14):                          # standing: the box stays where it is
        now[0] += 100
        still.append(t.processed([box(320)])["motion"])
    assert set(still) == {"still"}
    moving = []
    for step in range(14):                       # 0.8 m of view over 640 px: 40 px a step is 0.5 m/s
        now[0] += 100
        moving.append(t.processed([box(130 + step * 28)])["motion"])
    assert moving[-1] == "moving"


def test_the_two_zone_env_values_are_ignored_with_a_log_line(caplog):
    config = {**desk_config(GATE), "near_width": 0.25}
    with caplog.at_level(logging.WARNING):
        view = desk_view(config, SIZE, env={"TEACHER_DESK_SPLIT": "0.4", "TEACHER_DESK_DEAD_BAND": "0.02",
                                            "TEACHER_DESK_MIRROR": "0", "TEACHER_DESK_NEAR_WIDTH": "0.3"})
    assert (view.zones, view.mirror, view.near_width, view.dead_band) == ((1,), False, 0.3, 0.0)
    said = [r.getMessage() for r in caplog.records]
    assert len(said) == 2 and all("is ignored" in line and "one zone" in line for line in said)
    two = desk_view(desk_config(STRIP), SIZE, env={"TEACHER_DESK_SPLIT": "0.4"})    # two zones: still obeyed
    assert two.split == 0.4 and two.zones == (1, 2)


def test_preflight_and_the_near_calibration_take_the_file(tmp_path):
    path, mode = tmp_path / "calib.json", tmp_path / "label_mode"
    path.write_text(json.dumps(desk_config(GATE)))
    mode.write_text("off")
    view = check_files(path, mode, tmp_path / "heartbeat.json", SIZE, area_size("0.8x0.6"))
    assert isinstance(view, DeskView) and view.near_width is None and view.zones == (1,)
    beats = iter([{"frame": i, "box_w": 0.4 if i < 8 else 0.25} for i in range(16)])
    config = calibrate_near(path, lambda: next(beats), ask=lambda text: "", clock=lambda: 0, sleep=lambda s: None,
                            say=lambda text: None)
    assert config["near_width"] == 0.325 and config["zones"] == [1] and "split" not in config
    assert validate(json.loads(path.read_text()), SIZE).near(0.33 * SIZE[0])


def test_the_floor_view_gives_zone_1_anywhere_on_the_spot():
    area = area_of({"area_m": [0.8, 0.6], "zone_split_m": [None, None]})
    assert [zone_in(area, x, y) for x, y in ((0.0, 0.0), (0.4, 0.3), (0.8, 0.6), (0.79, 0.01))] == [1, 1, 1, 1]
    assert [zone_in(area, x, y) for x, y in ((-0.01, 0.3), (0.81, 0.3), (0.4, -0.01), (0.4, 0.61))] == [0, 0, 0, 0]
    area_m, split = area_from_nodes(GATE)
    corners = [[60, 300], [350, 320], [330, 220], [80, 210]]
    config = json.loads(json.dumps(calibration(corners, [400, 400], area_m=area_m, zone_split_m=split)))
    assert config["area_m"] == [0.8, 0.6] and config["zone_split_m"] == [None, None]
    for (u, v), expected in zip(corners, [[0, 0], [0.8, 0], [0.8, 0.6], [0, 0.6]]):
        point, zone = foot_point([u - 1, v - 10, u + 1, v], config)
        assert point == pytest.approx(expected, abs=1e-9) and zone == 1
    projection = Projection(config)
    assert projection.zone([0.4, 0.3]) == 1 and projection.zone([0.4, 0.7]) == 0
    assert validate(config, [400, 400]).area[:2] == (0.8, 0.6)
    sent = []
    label = Teacher(projection, sent.append, clock=lambda: 1000).processed(
        [dict(label="person", value=0.9, x=195, y=200, width=20, height=60)])
    assert label["present"] is True and label["zone"] == 1 and errors(label) == []
