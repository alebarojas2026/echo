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
