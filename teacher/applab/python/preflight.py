"""Check numeric teacher configuration without importing a camera or brick."""

import argparse
import json
import math
from pathlib import Path
import tempfile

try:
    from .labels import Projection
except ImportError:
    from labels import Projection


def box_size(text):
    try:
        width, height = [int(v) for v in text.lower().split("x")]
    except (ValueError, AttributeError):
        raise ValueError("box size must be WIDTHxHEIGHT in detector coordinate pixels") from None
    if width <= 0 or height <= 0:
        raise ValueError("box dimensions must be positive")
    return [width, height]


def validate(config, detector_size):
    size = config.get("image_size", [])
    side = config.get("side_m", 2.0)
    if len(size) != 2 or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in size):
        raise ValueError("calibration image_size must contain two positive integers")
    if not isinstance(side, (int, float)) or not math.isfinite(side) or side <= 0:
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
    side = projection.side
    for point, expected in zip(corners, [(0, 0), (side, 0), (side, side), (0, side)]):
        if len(point) != 2 or not all(math.isfinite(v) for v in point):
            raise ValueError("invalid corner coordinates")
        if not (0 <= point[0] < projection.width and 0 <= point[1] < projection.height):
            raise ValueError("calibration corner is outside detector coordinates")
        if math.dist(projection.point(*point), expected) > 1e-6:
            raise ValueError("stored corners and homography disagree")
    return projection


def check_files(calibration, mode_file, heartbeat, detector_size):
    try:
        config = json.loads(Path(calibration).read_text(encoding="utf-8"))
        projection = validate(config, detector_size)
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
    args = parser.parse_args()
    try:
        check_files(args.calibration, args.mode_file, args.heartbeat, args.box_size)
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    print("Teacher numeric configuration and shared directory are ready; camera and bus remain untested.")


if __name__ == "__main__":
    main()
