import copy
import json
from pathlib import Path
import runpy

import pytest

from teacher.applab.python.preflight import box_size, check_files, validate
from teacher.calibrate import calibration


def config():
    return calibration([[100, 300], [300, 300], [300, 100], [100, 100]], [400, 400])


def test_valid_geometry_and_no_mutation():
    data = config()
    before = copy.deepcopy(data)
    assert validate(data, [400, 400]).point(200, 200) == [1, 1]
    assert data == before


@pytest.mark.parametrize("bad", ["", "400", "0x400", "-1x400", "400xNaN", "400x400x400"])
def test_explicit_detector_dimensions(bad):
    with pytest.raises(ValueError):
        box_size(bad)


def test_box_size_parser():
    assert box_size("640X480") == [640, 480]


def test_dimension_mismatch_fails_before_camera():
    with pytest.raises(ValueError, match="differs"):
        validate(config(), [640, 480])


@pytest.mark.parametrize("kind", ["nan", "singular", "corners", "side", "size"])
def test_bad_projection_rejected(kind):
    data = config()
    if kind == "nan":
        data["homography"][0][0] = float("nan")
    elif kind == "singular":
        data["homography"][0] = [0, 0, 0]
    elif kind == "side":
        data["side_m"] = float("nan")
    elif kind == "size":
        data["image_size"] = [float("nan"), 400]
    else:
        data["corners_px"][0] = [200, 200]
    with pytest.raises(ValueError):
        validate(data, [400, 400])


def test_preflight_creates_no_persistent_artifact(tmp_path):
    calibration_file = tmp_path / "calib.json"
    mode_file = tmp_path / "label_mode"
    calibration_file.write_text(json.dumps(config()))
    mode_file.write_text("off\n")
    before = set(tmp_path.iterdir())
    check_files(calibration_file, mode_file, tmp_path / "heartbeat.json", [400, 400])
    assert set(tmp_path.iterdir()) == before
    mode_file.write_text("invalid")
    with pytest.raises(ValueError, match="label_mode"):
        check_files(calibration_file, mode_file, tmp_path / "heartbeat.json", [400, 400])


def test_missing_shared_directory_and_mode_file(tmp_path):
    path = tmp_path / "calib.json"
    mode = tmp_path / "label_mode"
    path.write_text(json.dumps(config()))
    with pytest.raises(ValueError, match="preflight failed"):
        check_files(path, mode, tmp_path / "heartbeat.json", [400, 400])
    mode.write_text("off")
    with pytest.raises(ValueError, match="mounted shared directory"):
        check_files(path, mode, tmp_path / "missing/heartbeat.json", [400, 400])


def test_app_rejects_bad_setup_before_importing_brick(tmp_path, monkeypatch):
    path = tmp_path / "calib.json"
    mode = tmp_path / "label_mode"
    path.write_text(json.dumps(config()))
    mode.write_text("off")
    directory = Path(__file__).resolve().parents[1] / "applab/python"
    monkeypatch.syspath_prepend(str(directory))
    for key, value in {"TEACHER_CALIB": path, "TEACHER_MODE_FILE": mode,
                       "TEACHER_HEARTBEAT": tmp_path / "heartbeat.json", "TEACHER_BOX_SIZE": "640x480"}.items():
        monkeypatch.setenv(key, str(value))
    with pytest.raises(ValueError, match="differs from detector"):
        runpy.run_path(str(directory / "main.py"), run_name="__main__")
