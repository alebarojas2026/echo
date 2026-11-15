"""Convert explicit processed-frame results into CONTRACTS.md v2 labels."""

from collections import deque
import json
import logging
import math
from pathlib import Path
from statistics import median
import time


def area_of(config):
    """(width, height, split_x, split_y) in metres for a calibration config. The area is where a
    person can stand: the square (side_m, split in four) or, with area_m and zone_split_m from
    nodes.json, the desk layout's strip, split along x only (split_y None)."""
    side = config.get("side_m", 2.0)
    w, h = config.get("area_m", [side, side])
    sx, sy = config.get("zone_split_m", [w / 2, h / 2])
    return w, h, sx, sy


def zone_in(area, x, y):
    """CONTRACTS.md section 3: 0 outside the area; the square's 1-4 (1 + (x >= sx) + 2*(y < sy)),
    or the strip's 1-2 (1 + (x >= sx)) when there is no split along y."""
    w, h, sx, sy = area
    if not (0 <= x <= w and 0 <= y <= h):
        return 0
    return 1 + int(x >= sx) + (2 * int(y < sy) if sy is not None else 0)


class Projection:
    sends_point = True   # the foot point on the floor goes out as foot_m

    def __init__(self, config):
        self.matrix = config["homography"]
        self.width, self.height = config["image_size"]
        self.area = area_of(config)
        self.side = self.area[0]
        if self.width <= 0 or self.height <= 0 or self.area[0] <= 0 or self.area[1] <= 0:
            raise ValueError("invalid calibration dimensions")
        if len(self.matrix) != 3 or any(len(row) != 3 for row in self.matrix):
            raise ValueError("homography must be 3 by 3")

    def corners_m(self):
        """The area's SW, SE, NE, NW corners in metres, the order they are clicked in."""
        w, h = self.area[:2]
        return [(0, 0), (w, 0), (w, h), (0, h)]

    def point(self, x, y):
        h = self.matrix
        d = h[2][0] * x + h[2][1] * y + h[2][2]
        if abs(d) < 1e-12:
            raise ValueError("point projects to infinity")
        p = [round((h[i][0] * x + h[i][1] * y + h[i][2]) / d, 12) for i in (0, 1)]
        if not all(math.isfinite(v) for v in p):
            raise ValueError("non-finite foot point")
        return p

    def zone(self, point):
        return zone_in(self.area, *point)


class DeskView:
    """Desk mode: the webcam sits on the desk facing the sensing strip and only tells left from right.

    config: {"mode": "desk", "image_size": [w, h], "split_u": the pixel column of the zone split,
    "u_range": [u_min, u_max] (the strip's ends in the image), "left_zone": the zone on the image's
    left (a desk camera looking out at the aisle sees east on its left), "area_m": [width, depth],
    "zone_split_m": [split_x, null]}, optional "box_h_range": [min, max] pixels for a person at the
    strip's distance. A person counts by the centre of their box (no feet needed). Their x along the
    strip is estimated from the column, only to tell moving from still; no floor point is sent.
    """
    sends_point = False

    def __init__(self, config):
        self.width, self.height = config["image_size"]
        self.split_u = float(config["split_u"])
        self.u_min, self.u_max = (float(v) for v in config["u_range"])
        self.left_zone = int(config["left_zone"])
        self.area = area_of(config)
        self.box_h = config.get("box_h_range")
        if self.width <= 0 or self.height <= 0 or not (0 <= self.u_min < self.split_u < self.u_max <= self.width):
            raise ValueError("desk view needs 0 <= u_min < split_u < u_max <= image width")
        if self.left_zone not in (1, 2) or self.area[3] is not None:
            raise ValueError("desk view is for the two-zone strip: left_zone 1 or 2, no split along y")

    def point(self, u, v, box_h=None):
        """Estimated (x, middle of the strip) for a box centred on column u, or None off the strip."""
        if not (self.u_min <= u <= self.u_max):
            return None
        if self.box_h and box_h is not None and not (self.box_h[0] <= box_h <= self.box_h[1]):
            return None
        w, h, sx, _ = self.area
        # piecewise: [u_min, split_u] and [split_u, u_max] each cover one zone's width
        f = (u - self.u_min) / (self.split_u - self.u_min) if u < self.split_u else 1 + (u - self.split_u) / (self.u_max - self.split_u)
        west_to_east = self.left_zone == 1        # the image's left is the strip's west
        g = f if west_to_east else 2 - f          # 0..2 from the west end to the east end
        x = g * sx if g <= 1 else sx + (g - 1) * (w - sx)
        return [round(x, 4), round(h / 2, 4)]

    def zone(self, point):
        return 0 if point is None else zone_in(self.area, *point)


def view_for(config):
    """The camera's view of the layout: desk mode, or the floor projection."""
    return DeskView(config) if config.get("mode") == "desk" else Projection(config)


class Motion:
    """Trailing 0.5 s coordinate median, then displacement over a full second."""
    def __init__(self):
        self.raw = deque()
        self.filtered = deque()

    def update(self, t, point):
        if point is None or (self.raw and (t <= self.raw[-1][0] or t - self.raw[-1][0] > 500)):
            self.raw.clear()
            self.filtered.clear()
        if point is None:
            return "still"
        self.raw.append((t, point))
        while self.raw and self.raw[0][0] < t - 500:
            self.raw.popleft()
        filtered = [median(p[i] for _, p in self.raw) for i in (0, 1)]
        self.filtered.append((t, filtered))
        while len(self.filtered) > 1 and self.filtered[1][0] <= t - 1000:
            self.filtered.popleft()
        old_t, old = self.filtered[0]
        if t - old_t < 1000:
            return "still"
        speed = math.dist(filtered, old) / ((t - old_t) / 1000)
        return "moving" if speed > 0.25 else "still"


class Teacher:
    def __init__(self, projection, send, mode=lambda: "person", clock=None, confidence=0.4):
        self.projection, self.send, self.mode = projection, send, mode
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.confidence = confidence
        self.frame = 0
        self.motion = Motion()

    def processed(self, boxes):
        """Called once for an explicit bounding_boxes list, including []."""
        t = self.clock()
        people = [b for b in boxes if b.get("label") == "person" and b.get("value", 0) >= self.confidence]
        candidates, clipped = [], False
        for b in people:
            x, y, w, h = (float(b[k]) for k in ("x", "y", "width", "height"))
            if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                raise ValueError("invalid person box")
            view = self.projection
            if view.sends_point:   # the floor: the foot point, and a box cut by any edge is clipped
                clipped |= x <= 0 or y <= 0 or x + w >= view.width or y + h >= view.height
                foot = view.point(x + w / 2, y + h)
            else:                  # the desk: the box centre; a close person fills the height, so only the sides clip
                clipped |= x <= 0 or x + w >= view.width
                foot = view.point(x + w / 2, y + h / 2, h)
            if foot is not None and view.zone(foot):
                candidates.append((foot, float(b["value"])))
        # Multiple people cannot be represented by the single-person label contract.
        clipped |= len(candidates) > 1
        point, conf = candidates[0] if len(candidates) == 1 else (None, 0.0)
        zone = self.projection.zone(point) if point else 0
        moving = self.motion.update(t, None if clipped else point)
        mode = self.mode()
        if mode not in {"person", "object", "off"}:
            raise ValueError("invalid label mode")
        self.frame += 1
        label = dict(v=2, type="label", t=t, seq=self.frame, src="live", frame=self.frame,
                     mode=mode, persons_in_frame=len(people), present=bool(candidates),
                     zone=None if clipped else zone,
                     foot_m=None if clipped or not self.projection.sends_point else point,
                     motion=moving if point is not None and not clipped else None, conf=conf, clipped=clipped)
        self.send(label)
        return label


def attach_processed_results(detector, teacher):
    """Observe results before the brick suppresses callbacks for empty frames.

    This narrow private hook must be checked against the installed brick version.
    No frame bytes are requested or retained. Missing/malformed results emit nothing.
    """
    original = detector._process_message
    reported = set()

    def process(ws, message):
        try:
            result = json.loads(message)
            boxes = result.get("result", {}).get("bounding_boxes") if result.get("type") == "classification" else None
            if isinstance(boxes, list):
                teacher.processed(boxes)
        except Exception as error:
            kind = type(error)
            if kind not in reported:
                logging.getLogger(__name__).exception("teacher result adapter failed (%s)", kind.__name__)
                reported.add(kind)
        return original(ws, message)

    detector._process_message = process


def read_mode(path):
    return Path(path).read_text().strip()
