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
    nodes.json, the desk layout's strip, split along x only (split_y None). A strip that is one
    spot has no split at all (split_x None too): one zone."""
    side = config.get("side_m", 2.0)
    w, h = config.get("area_m", [side, side])
    sx, sy = config.get("zone_split_m", [w / 2, h / 2])
    return w, h, sx, sy


def zone_in(area, x, y):
    """CONTRACTS.md section 3: 0 outside the area; the square's 1-4 (1 + (x >= sx) + 2*(y < sy)),
    or the strip's 1-2 (1 + (x >= sx)) when there is no split along y; 1 anywhere inside a strip
    with no split (one spot)."""
    w, h, sx, sy = area
    if not (0 <= x <= w and 0 <= y <= h):
        return 0
    if sx is None:
        return 1
    return 1 + int(x >= sx) + (2 * int(y < sy) if sy is not None else 0)


class Projection:
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


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)             or not low <= value <= high:
        raise ValueError(f"desk view {name} must be a number from {low} to {high}")
    return float(value)


class DeskView:
    """Left, right or nobody from the person box alone, for a webcam on the desk facing the strip.
    On a layout with one zone (one spot): somebody or nobody, with no side.

    From that close the camera sees a torso, never feet, so there is no floor point: only where the
    box's centre sits across the frame. The config (written by `python -m teacher.calibrate --desk`
    from radio/nodes.json) holds numbers only:
      split      where the zone split line is across the frame, 0 (left edge) to 1 (right edge)
      dead_band  half the width of the band around it where a label can't be trusted, same unit
      mirror     true when the camera faces the person, so the strip's low-x zone is on the right
      zones      [the zone below the split in x, the zone from the split up], from the zone rule
      view_m     how much of the strip the frame spans at the standing line, for the moving rule
      side_edge  "clipped" (a box cut by the left or right frame edge is dropped) or "keep"
      near_width how wide a person's box is, as a share of the frame width, when they stand in the
                 strip. A narrower box is someone standing back, behind the line of the arm
                 beacons, where no link sees them: never labelled present. It is measured, by
                 `python -m teacher.calibrate --near` (at the desk edge, then one step back).
                 Without it nobody is labelled present: the teacher does not guess a distance.
    A box cut by the top or bottom edge is normal here and is kept.
    One zone: zones is [that zone] and the file has no split and no dead_band. There is no line, so
    nothing is dropped around one; side_edge, near_width and the rest work as above.
    """
    def __init__(self, config, image_size):
        self.width, self.height = image_size
        if self.width <= 0 or self.height <= 0:
            raise ValueError("invalid detector dimensions")
        zones = config.get("zones")
        self.one_zone = isinstance(zones, list) and len(zones) == 1
        if self.one_zone:
            if config.get("split") is not None or config.get("dead_band") not in (None, 0, 0.0):
                raise ValueError("desk view with one zone has no split line and no dead band")
            self.split, self.dead_band = 0.5, 0.0   # the middle of the frame, only for metres along the strip
        else:
            self.split = _number(config.get("split"), "split", 0.05, 0.95)
            self.dead_band = _number(config.get("dead_band"), "dead_band", 0.0, 0.4)
        self.view_m = _number(config.get("view_m"), "view_m", 0.1, 100.0)
        self.mirror, self.side_edge = config.get("mirror"), config.get("side_edge", "clipped")
        self.near_width = (None if config.get("near_width") is None
                           else _number(config["near_width"], "near_width", 0.02, 1.0))
        if not isinstance(self.mirror, bool) or self.side_edge not in ("clipped", "keep"):
            raise ValueError("desk view needs mirror true or false and side_edge clipped or keep")
        if not isinstance(zones, list) or len(zones) not in (1, 2) or len(set(map(repr, zones))) != len(zones) \
                or not all(isinstance(z, int) and not isinstance(z, bool) and z > 0 for z in zones):
            raise ValueError("desk view zones must be the two zone ids either side of the split, or the one zone")
        self.zones = tuple(zones)

    def near(self, width):
        """True when a box this wide (pixels) is someone standing in the strip, False when they
        are standing back. Always False until near_width has been measured."""
        return self.near_width is not None and width / self.width >= self.near_width

    def side(self, x, width):
        """(zone, metres along the strip from the split line) for a box's left edge and width in
        pixels. zone is None when the label can't be trusted: the centre is inside the dead band,
        or the box is cut by a side edge of the frame (unless side_edge is keep)."""
        offset = (x + width / 2) / self.width - self.split
        cut = x <= 0 or x + width >= self.width
        if abs(offset) < self.dead_band or (cut and self.side_edge == "clipped"):
            zone = None
        elif self.one_zone:
            zone = self.zones[0]
        else:
            zone = self.zones[int((offset > 0) != self.mirror)]
        return zone, (-offset if self.mirror else offset) * self.view_m


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
        self.box_w = None   # desk view: the one person's box width as a share of the frame, for calibration

    def processed(self, boxes):
        """Called once for an explicit bounding_boxes list, including []."""
        t = self.clock()
        people = [b for b in boxes if b.get("label") == "person" and b.get("value", 0) >= self.confidence]
        sized = []
        for b in people:
            x, y, w, h = (float(b[k]) for k in ("x", "y", "width", "height"))
            if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
                raise ValueError("invalid person box")
            sized.append((x, y, w, h, float(b["value"])))
        view = self._desk if isinstance(self.projection, DeskView) else self._floor
        present, zone, point, track, conf, clipped = view(sized)
        moving = self.motion.update(t, None if clipped else track)
        mode = self.mode()
        if mode not in {"person", "object", "off"}:
            raise ValueError("invalid label mode")
        self.frame += 1
        label = dict(v=2, type="label", t=t, seq=self.frame, src="live", frame=self.frame,
                     mode=mode, persons_in_frame=len(people), present=present,
                     zone=None if clipped else zone, foot_m=None if clipped else point,
                     motion=moving if track is not None and not clipped else None, conf=conf, clipped=clipped)
        self.send(label)
        return label

    def _floor(self, people):
        """(present, zone, foot point, point to track for motion, conf, clipped) from foot points."""
        candidates, clipped = [], False
        for x, y, w, h, value in people:
            edge = x <= 0 or y <= 0 or x + w >= self.projection.width or y + h >= self.projection.height
            clipped |= edge
            foot = self.projection.point(x + w / 2, y + h)
            if self.projection.zone(foot):
                candidates.append((foot, value))
        # Multiple people cannot be represented by the single-person label contract.
        clipped |= len(candidates) > 1
        point, conf = candidates[0] if len(candidates) == 1 else (None, 0.0)
        return bool(candidates), self.projection.zone(point) if point else 0, point, point, conf, clipped

    def _desk(self, people):
        """The same from the box's place across the frame. There is no foot point, so foot_m is null;
        motion follows the box centre along the strip. Someone standing back (a box narrower than
        near_width) is in view but not in the strip: clipped, never present, so the window is
        dropped and the radio is not taught that links nobody is touching can mean a person."""
        self.box_w = round(people[0][2] / self.projection.width, 4) if len(people) == 1 else None
        if len(people) != 1:
            return bool(people), 0, None, None, 0.0, len(people) > 1
        x, _, w, _, value = people[0]
        if not self.projection.near(w):
            return False, 0, None, None, 0.0, True
        zone, along_m = self.projection.side(x, w)
        return True, zone, None, [along_m, 0.0], value, zone is None


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
