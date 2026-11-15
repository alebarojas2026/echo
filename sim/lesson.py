"""The live lesson as a scripted path: the camera teaches left and right, then it is unplugged.

    python -m sim.fake lesson      # the feed: radio, and desk-view labels until the camera goes
    python -m sim.state lesson     # the fake brain's states, for building the screen

Timeline, in seconds: someone steps up at ARRIVE_S and keeps stepping left and right (STAND_S on
each side) until the end. The screen starts the recording at RECORD_S and sends train at TRAIN_S;
the camera is unplugged at CAM_OFF_S and the recording is stopped at STOP_S.

Where "left" and "right" are comes from the layout in radio/nodes.json: the centres of zones 1
and 2 (the two sides of the desk strip; on the square, its two northern zones).
"""
from .layout import LAYOUT

ARRIVE_S, RECORD_S, TRAIN_S, CAM_OFF_S, STOP_S, END_S = 3.0, 5.0, 25.0, 45.0, 62.0, 66.0
STAND_S, MOVE_S = 3.0, 1.0
REFIT_S = 15.0
DEAD_BAND_M = 0.1         # the camera gives no label this close to the split line
AGREE = (6, 8, 9)         # the fake brain's "N of 10" after its first, second and later fits
SESSION = "sim-lesson"


def sides(layout=LAYOUT):
    """((zone, (x, y)), (zone, (x, y))): where a person stands on the left, then on the right."""
    left, right = sorted(layout.centres)[:2]   # zones 1 and 2: either side of the split in both layouts
    return tuple((layout.zone_of(*layout.centres[z]), layout.centres[z]) for z in (left, right))


def split_x(layout=LAYOUT) -> float:
    return layout.split_x_m if layout.strip_m else layout.size_m[0] / 2


def stands(layout=LAYOUT):
    """[(from s, to s, zone)]: every stretch the person stands on one side, in order."""
    out, t, i = [], ARRIVE_S, 0
    while t + STAND_S <= END_S:
        out.append((t, t + STAND_S, sides(layout)[i % 2][0]))
        t, i = t + STAND_S + MOVE_S, i + 1
    return out


def path(layout=LAYOUT) -> dict:
    spot = dict(sides(layout))
    person = [{"t": 0, "x": None}]
    for start, end, zone in stands(layout):
        x, y = spot[zone]
        person += [{"t": start, "x": x, "y": y}, {"t": end, "x": x, "y": y}]
    return {"name": "lesson", "duration_s": END_S, "person": person,
            "about": "The camera on the desk teaches left and right for 20 s, the model is fit, the camera "
                     "is unplugged at 45 s and the radio carries on.",
            "meta": {"session": SESSION, "purpose": "train", "walker": "sim"},
            "teacher": "desk", "dead_band_m": DEAD_BAND_M,
            "camera": [{"t": 0, "state": "on"}, {"t": CAM_OFF_S, "state": "off"}],
            "lesson": {"record_at": RECORD_S, "train_at": TRAIN_S, "refit_s": REFIT_S,
                       "stop_at": STOP_S, "agree": list(AGREE)}}


def fit_times(lesson: dict, cam_off: float) -> list:
    """When the fake brain's fits finish: at train, every refit_s while the camera is on, and one
    last time when the camera goes (or the recording stops, whichever is first)."""
    end = min(cam_off, lesson.get("stop_at", cam_off))
    out, t = [], lesson["train_at"]
    while t < end:
        out.append(t)
        t += lesson["refit_s"]
    return out + [end]
