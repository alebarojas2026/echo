"""Click measured SW, SE, NE, NW floor corners; save numbers only."""

import argparse
import json
import math
from pathlib import Path


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


def calibration(corners, image_size, side_m=2.0):
    if len(corners) != 4 or len(image_size) != 2:
        raise ValueError("four corners and an image size are required")
    width, height = image_size
    if width <= 0 or height <= 0 or not math.isfinite(side_m) or side_m <= 0:
        raise ValueError("invalid dimensions")
    for x, y in corners:
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < width and 0 <= y < height):
            raise ValueError("corner outside the camera view")
    crosses = []
    for i in range(4):
        a, b, c = (corners[(i + j) % 4] for j in range(3))
        crosses.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if not (all(v > 1e-8 for v in crosses) or all(v < -1e-8 for v in crosses)):
        raise ValueError("corners must form a convex square outline in SW, SE, NE, NW order")
    matrix, rhs = [], []
    for (u, v), (x, y) in zip(corners, [(0, 0), (side_m, 0), (side_m, side_m), (0, side_m)]):
        matrix.extend([[u, v, 1, 0, 0, 0, -x*u, -x*v],
                       [0, 0, 0, u, v, 1, -y*u, -y*v]])
        rhs.extend([x, y])
    h = solve(matrix, rhs) + [1.0]
    return {"image_size": list(image_size), "side_m": side_m,
            "corners_px": corners, "corner_order": ["SW", "SE", "NE", "NW"],
            "homography": [h[:3], h[3:6], h[6:]]}


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
    side = config["side_m"]
    zone = 0 if not (0 <= x <= side and 0 <= y <= side) else 1 + int(x >= side/2) + 2 * int(y < side/2)
    return [x, y], zone


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
    parser.add_argument("--side-m", type=float, default=2.0)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("calib.json"))
    args = parser.parse_args()
    points, size = click_corners(args.device)
    config = calibration(points, size, args.side_m)
    args.output.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
    print(f"Saved corner coordinates and projection to {args.output}")


if __name__ == "__main__":
    main()
