import json
from pathlib import Path

import pytest

from teacher.calibrate import calibration, foot_point


def test_box_coordinates_without_images():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/boxes.json").read_text())
    config = calibration(fixture["corners_px"], fixture["image_size"])
    for case in fixture["cases"]:
        point, zone = foot_point(case["box"], config)
        assert point == pytest.approx(case["foot_m"])
        assert zone == case["zone"]
    assert json.loads(json.dumps(config)) == config


def test_perspective_corners_and_scaled_square():
    corners = [[60, 300], [350, 320], [270, 80], [130, 60]]
    config = calibration(corners, [400, 400], 1.5)
    for (u, v), expected in zip(corners, [[0, 0], [1.5, 0], [1.5, 1.5], [0, 1.5]]):
        point, _ = foot_point([u - 1, v - 10, u + 1, v], config)
        assert point == pytest.approx(expected, abs=1e-10)


@pytest.mark.parametrize("corners", [
    [[1, 1]] * 4,
    [[10, 10], [20, 20], [30, 30], [40, 40]],
    [[100, 300], [300, 100], [300, 300], [100, 100]],
    [[-1, 300], [300, 300], [300, 100], [100, 100]],
])
def test_bad_corners_rejected(corners):
    with pytest.raises(ValueError):
        calibration(corners, [400, 400])


def test_invalid_box_rejected():
    config = calibration([[100, 300], [300, 300], [300, 100], [100, 100]], [400, 400])
    with pytest.raises(ValueError):
        foot_point([10, 10, 5, 20], config)


def test_area_from_nodes_json_square_and_strip():
    from teacher.calibrate import NODES, area_from_nodes
    nodes = json.loads(NODES.read_text())
    if not nodes["frame"].get("strip_m"):
        assert area_from_nodes(nodes) == ([2.0, 2.0], [1.0, 1.0])                        # the old square
    assert area_from_nodes({"frame": {"size_m": [2.0, 2.0]}}) == ([2.0, 2.0], [1.0, 1.0])
    strip = {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}
    assert area_from_nodes(strip) == ([1.6, 0.6], [0.8, None])                           # the desk layout


def test_strip_calibration_maps_corners_and_gives_two_zones():
    from teacher.applab.python.labels import Projection
    from teacher.applab.python.preflight import validate
    corners = [[60, 300], [350, 320], [330, 220], [80, 210]]
    config = calibration(corners, [400, 400], area_m=[1.6, 0.6], zone_split_m=[0.8, None])
    assert config["area_m"] == [1.6, 0.6] and config["zone_split_m"] == [0.8, None]
    for (u, v), expected in zip(corners, [[0, 0], [1.6, 0], [1.6, 0.6], [0, 0.6]]):
        point, _ = foot_point([u - 1, v - 10, u + 1, v], config)
        assert point == pytest.approx(expected, abs=1e-10)
    proj = Projection(json.loads(json.dumps(config)))
    assert [proj.zone(p) for p in ([0.4, 0.3], [1.2, 0.3], [0.79, 0.59], [0.8, 0.0], [1.2, 0.7], [-0.1, 0.3])] == [1, 2, 1, 2, 0, 0]
    assert validate(json.loads(json.dumps(config)), [400, 400]).area == (1.6, 0.6, 0.8, None)


def test_square_configs_without_area_keep_four_zones():
    from teacher.applab.python.labels import Projection
    config = calibration([[100, 300], [300, 300], [300, 100], [100, 100]], [400, 400])
    assert "area_m" not in config
    proj = Projection(config)
    assert [proj.zone(p) for p in ([0.5, 1.5], [1.5, 1.5], [0.5, 0.5], [1.5, 0.5], [2.1, 1.0])] == [1, 2, 3, 4, 0]
