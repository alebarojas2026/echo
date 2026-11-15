"""The desk layout's strip: calibration, labels against the contract, and refusing a square calibration."""

import json
from pathlib import Path
import runpy
import sys

import pytest

from contracts.check import errors
from teacher.applab.python.labels import Projection, Teacher
from teacher.applab.python.preflight import area_size, check_files
from teacher.calibrate import NODES, area_from_nodes, area_text, calibration, foot_point

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures/boxes.json").read_text(encoding="utf-8"))
SQUARE_CORNERS = [[100, 300], [300, 300], [300, 100], [100, 100]]


def repo_layout():
    return json.loads(NODES.read_text(encoding="utf-8"))


def strip_nodes():
    """radio/nodes.json when it is the two-zone desk layout, else a stand-in with the same frame keys
    (the square, or the one spot, which test_one_zone.py covers)."""
    nodes = repo_layout()
    if (nodes.get("frame") or {}).get("strip_m") == [1.6, 0.6] and nodes["frame"].get("zone_split_x_m") == 0.8:
        return nodes
    return {"frame": {"size_m": [1.6, 1.1], "strip_m": [1.6, 0.6], "zone_split_x_m": 0.8}}


def strip_config(corners, size=(400, 400)):
    area_m, split = area_from_nodes(strip_nodes())
    return calibration(corners, list(size), area_m=area_m, zone_split_m=split)


def pixel(config, x, y):
    """Floor metres back to pixels, through the inverse of the stored homography."""
    (a, b, c), (d, e, f), (g, h, i) = config["homography"]
    inv = [[e*i - f*h, c*h - b*i, b*f - c*e], [f*g - d*i, a*i - c*g, c*d - a*f], [d*h - e*g, b*g - a*h, a*e - b*d]]
    w = inv[2][0] * x + inv[2][1] * y + inv[2][2]
    return [(inv[r][0] * x + inv[r][1] * y + inv[r][2]) / w for r in (0, 1)]


def person(u, v):
    return {"label": "person", "value": 0.9, "x": u - 10, "y": v - 60, "width": 20, "height": 60}


def test_strip_area_comes_from_nodes_json():
    assert area_from_nodes(strip_nodes()) == ([1.6, 0.6], [0.8, None])


def test_strip_corners_and_labels_pass_the_contract():
    corners = [[60, 300], [350, 320], [330, 220], [80, 210]]
    config = json.loads(json.dumps(strip_config(corners)))
    assert config["area_m"] == [1.6, 0.6] and config["zone_split_m"] == [0.8, None]
    for (u, v), expected in zip(corners, [[0, 0], [1.6, 0], [1.6, 0.6], [0, 0.6]]):
        assert foot_point([u - 1, v - 10, u + 1, v], config)[0] == pytest.approx(expected, abs=1e-9)
    teacher = Teacher(Projection(config), send=lambda label: None, clock=lambda: 1000)
    cases = [((0.4, 0.3), True, 1), ((0.8, 0.3), True, 2), ((1.2, 0.3), True, 2),
             ((1.7, 0.3), False, 0), ((0.4, 0.7), False, 0)]
    for (x, y), present, zone in cases:
        label = teacher.processed([person(*pixel(config, x, y))])
        assert (label["present"], label["zone"], label["clipped"]) == (present, zone, False), (x, y)
        assert label["foot_m"] == (pytest.approx([x, y], abs=1e-9) if present else None)
        assert errors(label) == [], (x, y)


@pytest.mark.parametrize("case", FIXTURE["strip"]["cases"], ids=lambda c: str(c["foot_m"]))
def test_strip_fixture_boxes(case):
    strip = FIXTURE["strip"]
    config = calibration(strip["corners_px"], strip["image_size"], area_m=strip["area_m"],
                         zone_split_m=strip["zone_split_m"])
    point, zone = foot_point(case["box"], config)
    assert point == pytest.approx(case["foot_m"], abs=1e-9)
    assert zone == case["zone"]


def test_fixture_keeps_the_square_set():
    assert len(FIXTURE["cases"]) == 6 and "area_m" not in FIXTURE
    assert sorted({c["zone"] for c in FIXTURE["strip"]["cases"]}) == [0, 1, 2]


@pytest.mark.parametrize("text, area", [("1.6x0.6", [1.6, 0.6]), ("2X2", [2.0, 2.0])])
def test_area_size_parser(text, area):
    assert area_size(text) == area


@pytest.mark.parametrize("bad", ["", "1.6", "0x0.6", "-1x2", "nanx1", "1x2x3", "infx1"])
def test_area_size_rejects(bad):
    with pytest.raises(ValueError):
        area_size(bad)


def files(tmp_path, config):
    path, mode = tmp_path / "calib.json", tmp_path / "label_mode"
    path.write_text(json.dumps(config))
    mode.write_text("off")
    return path, mode, tmp_path / "heartbeat.json"


def test_square_calibration_refused_for_the_strip(tmp_path):
    square = calibration(SQUARE_CORNERS, [400, 400])
    with pytest.raises(ValueError, match="2 x 2 m area but the layout's is 1.6 x 0.6 m; recalibrate"):
        check_files(*files(tmp_path, square), [400, 400], area_size("1.6x0.6"))
    assert check_files(*files(tmp_path, square), [400, 400], area_size("2x2")).area[:2] == (2.0, 2.0)
    assert check_files(*files(tmp_path, square), [400, 400]).area[:2] == (2.0, 2.0)   # no area given: not checked


def test_strip_calibration_refused_for_the_square(tmp_path):
    strip = strip_config(FIXTURE["strip"]["corners_px"])
    assert check_files(*files(tmp_path, strip), [400, 400], area_size("1.6x0.6")).area[:2] == (1.6, 0.6)
    with pytest.raises(ValueError, match="recalibrate"):
        check_files(*files(tmp_path, strip), [400, 400], area_size("2x2"))


def test_repo_layout_decides_which_calibration_passes(tmp_path):
    """On the square the old calibration passes; once nodes.json is a strip (two zones or one spot) it is
    refused, and a calibration made for that strip passes."""
    area_m, split = area_from_nodes(repo_layout())
    expected = area_size(area_text(area_m))
    square = calibration(SQUARE_CORNERS, [400, 400])
    if split[1] is None:
        with pytest.raises(ValueError, match="recalibrate"):
            check_files(*files(tmp_path, square), [400, 400], expected)
        strip = calibration(FIXTURE["strip"]["corners_px"], [400, 400], area_m=area_m, zone_split_m=split)
        assert check_files(*files(tmp_path, strip), [400, 400], expected)
    else:
        assert check_files(*files(tmp_path, square), [400, 400], expected)


def test_host_preflight_reads_the_area_from_nodes_json(tmp_path, monkeypatch, capsys):
    path, mode, heartbeat = files(tmp_path, calibration(SQUARE_CORNERS, [400, 400]))
    monkeypatch.delenv("TEACHER_AREA", raising=False)
    monkeypatch.setattr(sys, "argv", ["preflight", "--calibration", str(path), "--mode-file", str(mode),
                                      "--heartbeat", str(heartbeat), "--box-size", "400x400"])
    square_layout = area_from_nodes(repo_layout())[1][1] is not None
    if square_layout:
        runpy.run_module("teacher.preflight", run_name="__main__")
        assert "ready" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit) as stop:
            runpy.run_module("teacher.preflight", run_name="__main__")
        assert stop.value.code == 1 and "recalibrate" in capsys.readouterr().err


def test_app_refuses_square_calibration_when_teacher_area_is_the_strip(tmp_path, monkeypatch):
    path, mode, heartbeat = files(tmp_path, calibration(SQUARE_CORNERS, [400, 400]))
    directory = Path(__file__).resolve().parents[1] / "applab/python"
    monkeypatch.syspath_prepend(str(directory))
    for key, value in {"TEACHER_CALIB": path, "TEACHER_MODE_FILE": mode, "TEACHER_HEARTBEAT": heartbeat,
                       "TEACHER_BOX_SIZE": "400x400", "TEACHER_AREA": "1.6x0.6"}.items():
        monkeypatch.setenv(key, str(value))
    with pytest.raises(ValueError, match="recalibrate"):
        runpy.run_path(str(directory / "main.py"), run_name="__main__")
