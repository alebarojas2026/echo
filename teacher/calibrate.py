"""Click measured SW, SE, NE, NW floor corners; save numbers only.

The corners are those of the area a person stands in, from radio/nodes.json: the 2 x 2 m square
(frame.size_m), or on the desk layout the strip (frame.strip_m, split at frame.zone_split_x_m).
"""

import argparse
import json
import math
from pathlib import Path

from teacher.applab.python.labels import DeskView, area_of, zone_in

NODES = Path(__file__).resolve().parents[1] / "radio" / "nodes.json"


def area_from_nodes(nodes):
    """(area_m, zone_split_m) from a parsed nodes.json: the strip when the frame has one, else the square."""
    frame = nodes.get("frame") or {}
    if frame.get("strip_m") and frame.get("zone_split_x_m") is not None:
        w, h = frame["strip_m"]
        return [w, h], [frame["zone_split_x_m"], None]
    w, h = frame.get("size_m") or [2.0, 2.0]
    return [w, h], [w / 2, h / 2]


def solve(matrix, rhs):
    rows = [list(map(float, row)) + [float(b)] for row, b in zip(matrix, rhs)]
    n = len(rows)
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(rows[i][col]))
        if abs(rows[pivot][col]) < 1e-10:
            raise ValueError("degenerate calibration corners")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        scale = rows[col][col]
        rows[col] = [v / scale for v in rows[col]]
        for i in range(n):
            if i != col:
                scale = rows[i][col]
                rows[i] = [v - scale * p for v, p in zip(rows[i], rows[col])]
    return [row[-1] for row in rows]


def desk_calibration(image_size, split_u, u_range, left_zone, nodes, box_h_range=None):
    """Desk mode (a webcam on the desk facing the strip): which pixel column splits the zones and
    where the strip's ends are in the image. Numbers only; the layout comes from nodes.json."""
    area_m, split = area_from_nodes(nodes)
    if split[1] is not None:
        raise ValueError("desk mode needs the desk layout's strip in nodes.json")
    config = {"mode": "desk", "image_size": list(image_size), "split_u": split_u, "u_range": list(u_range),
              "left_zone": left_zone, "area_m": area_m, "zone_split_m": split}
    if box_h_range:
        config["box_h_range"] = list(box_h_range)
    DeskView(config)   # raises if the numbers don't make sense
    return config


def calibration(corners, image_size, side_m=2.0, area_m=None, zone_split_m=None):
    """The projection from clicked pixels to metres. With area_m (and zone_split_m), the area is
    that rectangle; without, the side_m square split in four."""
    if len(corners) != 4 or len(image_size) != 2:
        raise ValueError("four corners and an image size are required")
    width, height = image_size
    w, h = area_m if area_m else (side_m, side_m)
    if width <= 0 or height <= 0 or not all(math.isfinite(v) and v > 0 for v in (w, h)):
        raise ValueError("invalid dimensions")
    for x, y in corners:
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < width and 0 <= y < height):
            raise ValueError("corner outside the camera view")
    crosses = []
    for i in range(4):
        a, b, c = (corners[(i + j) % 4] for j in range(3))
        crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if not (all(v > 1e-8 for v in crosses) or all(v < -1e-8 for v in crosses)):
        raise ValueError("corners must form a convex outline in SW, SE, NE, NW order")
    matrix, rhs = [], []
    for (u, v), (x, y) in zip(corners, [(0, 0), (w, 0), (w, h), (0, h)]):
        matrix.extend([[u, v, 1, 0, 0, 0, -x*u, -x*v],
                       [0, 0, 0, u, v, 1, -y*u, -y*v]])
        rhs.extend([x, y])
    m = solve(matrix, rhs) + [1.0]
    config = {"image_size": list(image_size), "side_m": side_m if not area_m else max(w, h),
              "corners_px": corners, "corner_order": ["SW", "SE", "NE", "NW"],
              "homography": [m[:3], m[3:6], m[6:]]}
    if area_m:
        config["area_m"] = [w, h]
        config["zone_split_m"] = list(zone_split_m) if zone_split_m else [w / 2, h / 2]
    return config


def foot_point(box, config):
    """Project an xyxy box; return metres and zone (0 outside)."""
    x1, y1, x2, y2 = box
    if not all(math.isfinite(v) for v in box) or x2 <= x1 or y2 <= y1:
        raise ValueError("invalid box")
    u, v = (x1 + x2) / 2, y2
    h = config["homography"]
    d = h[2][0] * u + h[2][1] * v + h[2][2]
    if abs(d) < 1e-12:
        raise ValueError("foot point projects to infinity")
    x, y = [round((h[i][0] * u + h[i][1] * v + h[i][2]) / d, 12) for i in (0, 1)]
    return [x, y], zone_in(area_of(config), x, y)


def click_corners(device):
    import cv2

    cap = cv2.VideoCapture(device)
    points = []
    window = "Radio Sight: click SW, SE, NE, NW; Enter accepts; R resets; Esc cancels"

    def click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append([x, y])

    try:
        ok, view = cap.read()
        if not ok:
            raise RuntimeError("camera did not return a frame")
        size = [view.shape[1], view.shape[0]]
        cv2.namedWindow(window)
        cv2.setMouseCallback(window, click)
        while True:
            overlay = view.copy()
            for name, (x, y) in zip(["SW", "SE", "NE", "NW"], points):
                cv2.circle(overlay, (x, y), 5, (0, 255, 0), -1)
                cv2.putText(overlay, name, (x + 8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow(window, overlay)
            key = cv2.waitKey(20) & 255
            if key == 27:
                raise RuntimeError("calibration cancelled")
            if key in (ord("r"), ord("R")):
                points.clear()
            if key in (10, 13) and len(points) == 4:
                return points, size
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--nodes", type=Path, default=NODES, help="radio/nodes.json, for the area's size and zones")
    parser.add_argument("--side-m", type=float, default=None, help="a square of this side instead of nodes.json")
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("calib.json"))
    parser.add_argument("--desk", action="store_true",
                        help="desk mode: no clicks, give --image-size, --split-u, --u-range and --left-zone")
    parser.add_argument("--image-size", help="detector box frame, WIDTHxHEIGHT (desk mode)")
    parser.add_argument("--split-u", type=float, help="pixel column of the zone split (desk mode)")
    parser.add_argument("--u-range", type=float, nargs=2, help="pixel columns of the strip's two ends (desk mode)")
    parser.add_argument("--left-zone", type=int, choices=(1, 2), help="zone on the image's left (desk mode)")
    args = parser.parse_args()
    if args.desk:
        size = [int(v) for v in args.image_size.lower().split("x")]
        config = desk_calibration(size, args.split_u, args.u_range, args.left_zone,
                                  json.loads(args.nodes.read_text(encoding="utf-8")))
        args.output.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
        print(f"Saved the desk view to {args.output}")
        return
    if args.side_m:
        area_m, split = None, None
    else:
        area_m, split = area_from_nodes(json.loads(args.nodes.read_text(encoding="utf-8")))
        print(f"area {area_m[0]} x {area_m[1]} m from {args.nodes}: click its SW, SE, NE, NW corners")
    points, size = click_corners(args.device)
    config = calibration(points, size, args.side_m or 2.0, area_m, split)
    args.output.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
    print(f"Saved corner coordinates and projection to {args.output}")


if __name__ == "__main__":
    main()
