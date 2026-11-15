"""Check numeric teacher configuration without importing a camera or brick."""

import argparse
import json
import math
import os
from pathlib import Path
import tempfile

try:
    from .labels import DeskView, Projection
except ImportError:
    from labels import DeskView, Projection

# The desk view's numbers can be tuned on the board without a new file: set one of these and restart the app.
DESK_ENV = {"TEACHER_DESK_SPLIT": "split", "TEACHER_DESK_DEAD_BAND": "dead_band",
            "TEACHER_DESK_MIRROR": "mirror", "TEACHER_DESK_SIDE_EDGE": "side_edge",
            "TEACHER_DESK_NEAR_WIDTH": "near_width"}
NO_NEAR = ("NOT READY FOR A LESSON: calib.json has no near_width, so the desk view can't tell someone in the "
           "strip from someone standing back, and labels nobody as present. Run "
           "`python -m teacher.calibrate --near` (stand at the desk edge, then one step back).")


def box_size(text):
    try:
        width, height = [int(v) for v in text.lower().split("x")]
    except (ValueError, AttributeError):
        raise ValueError("box size must be WIDTHxHEIGHT in detector coordinate pixels") from None
    if width <= 0 or height <= 0:
        raise ValueError("box dimensions must be positive")
    return [width, height]


def desk_view(config, detector_size, env=None):
    """The desk view (left / right from the box alone) for a config with "view": "desk"."""
    config = dict(config)
    for name, key in DESK_ENV.items():
        text = (os.environ if env is None else env).get(name, "").strip()
        if not text:
            continue
        if key == "side_edge":
            config[key] = text
        elif key == "mirror":
            if text not in ("0", "1"):
                raise ValueError(f"{name} must be 1 (the camera faces the person) or 0")
            config[key] = text == "1"
        else:
            try:
                config[key] = float(text)
            except ValueError:
                raise ValueError(f"{name} must be a number") from None
    return DeskView(config, detector_size)


def validate(config, detector_size):
    if config.get("view") == "desk":
        return desk_view(config, detector_size)
    size = config.get("image_size", [])
    dims = [config.get("side_m", 2.0), *config.get("area_m", [])]
    if len(size) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in size):
        raise ValueError("calibration image_size must contain two positive integers")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in dims):
        raise ValueError("floor side must be positive and finite")
    projection = Projection(config)
    h = projection.matrix
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for row in h for v in row):
        raise ValueError("homography must contain finite numeric coefficients")
    det = (h[0][0] * (h[1][1]*h[2][2] - h[1][2]*h[2][1])
           - h[0][1] * (h[1][0]*h[2][2] - h[1][2]*h[2][0])
           + h[0][2] * (h[1][0]*h[2][1] - h[1][1]*h[2][0]))
    if abs(det) < 1e-12:
        raise ValueError("homography is singular")
    if list(config["image_size"]) != list(detector_size):
        raise ValueError("calibration image_size differs from detector box coordinates; recalibrate in that frame")
    corners = config.get("corners_px")
    if not isinstance(corners, list) or len(corners) != 4 or config.get("corner_order") != ["SW", "SE", "NE", "NW"]:
        raise ValueError("calibration must include measured SW, SE, NE, NW corners")
    for point, expected in zip(corners, projection.corners_m()):
        if len(point) != 2 or not all(math.isfinite(v) for v in point):
            raise ValueError("invalid corner coordinates")
        if not (0 <= point[0] < projection.width and 0 <= point[1] < projection.height):
            raise ValueError("calibration corner is outside detector coordinates")
        if math.dist(projection.point(*point), expected) > 1e-6:
            raise ValueError("stored corners and homography disagree")
    return projection


def area_size(text):
    """TEACHER_AREA, the layout's area as WIDTHxHEIGHT in metres (calibrate prints it from nodes.json)."""
    try:
        width, height = [float(v) for v in text.lower().split("x")]
    except (ValueError, AttributeError):
        raise ValueError("layout area must be WIDTHxHEIGHT in metres, e.g. the value calibrate prints") from None
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("layout area must be positive and finite")
    return [width, height]


def check_area(projection, expected):
    """Refuse a calibration made for another area, e.g. the old square once the layout is the strip.
    The desk view has no floor area (left/right only), so there is nothing to compare."""
    if getattr(projection, "area", None) is None:
        return
    w, h = projection.area[:2]
    if expected and not all(abs(a - b) <= 1e-6 for a, b in zip((w, h), expected)):
        raise ValueError(f"calibration is for a {w:g} x {h:g} m area but the layout's is "
                         f"{expected[0]:g} x {expected[1]:g} m; recalibrate with python -m teacher.calibrate")


def check_files(calibration, mode_file, heartbeat, detector_size, area=None):
    """area: the layout's [width, height] in metres; None skips the area check."""
    try:
        config = json.loads(Path(calibration).read_text(encoding="utf-8"))
        projection = validate(config, detector_size)
        check_area(projection, area)
        mode = Path(mode_file).read_text(encoding="utf-8").strip()
        if mode not in {"off", "person", "object"}:
            raise ValueError("label_mode must contain off, person or object")
        target = Path(heartbeat)
        if target.is_dir() or not target.parent.is_dir():
            raise ValueError("heartbeat needs a file path inside the mounted shared directory")
        # Test directory replacement permissions with numeric text, never camera data.
        with tempfile.TemporaryFile(mode="w+", dir=target.parent, encoding="utf-8") as probe:
            probe.write('{"probe":true}')
            probe.flush()
        return projection
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError(f"teacher preflight failed: {error}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--mode-file", required=True, type=Path)
    parser.add_argument("--heartbeat", required=True, type=Path)
    parser.add_argument("--box-size", required=True, type=box_size)
    parser.add_argument("--area", type=area_size, default=os.environ.get("TEACHER_AREA"),
                        help="the layout's area, WIDTHxHEIGHT metres (default TEACHER_AREA)")
    args = parser.parse_args()
    try:
        view = check_files(args.calibration, args.mode_file, args.heartbeat, args.box_size, args.area)
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    if isinstance(view, DeskView) and view.near_width is None:
        parser.exit(1, NO_NEAR + "\n")   # the app still starts, so the calibration can read its heartbeat
    print("Teacher numeric configuration and shared directory are ready; camera and bus remain untested.")


if __name__ == "__main__":
    main()
