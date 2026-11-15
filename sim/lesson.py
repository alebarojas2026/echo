"""The live lesson as a scripted path: the camera teaches left and right, then it is unplugged.

    python -m sim.fake lesson      # the feed: radio, and desk-view labels until the camera goes
    python -m sim.state lesson     # the fake brain's states, for building the screen

Timeline, in seconds: the screen starts the recording at RECORD_S with nobody there, so the
lesson begins with empty time. Someone steps up at ARRIVE_S and steps left and right (STAND_S on
each side), steps right out of view from OUT_S to BACK_S (a second piece of empty time), and
comes back and keeps stepping until the end. The screen sends train at TRAIN_S; the camera is
unplugged at CAM_OFF_S and the recording is stopped at STOP_S. Without the empty time the model
learns a ghost: it has never seen what the links look like with nobody there.

Where "left" and "right" are comes from the layout in radio/nodes.json: the centres of zones 1
and 2 (the two sides of the desk strip; on the square, its two northern zones).
"""
from .layout import LAYOUT

RECORD_S, ARRIVE_S, OUT_S, BACK_S, TRAIN_S, CAM_OFF_S, STOP_S, END_S = 2.0, 10.0, 22.0, 27.0, 31.0, 51.0, 68.0, 72.0
STAND_S, MOVE_S = 3.0, 1.0
REFIT_S = 15.0
DEAD_BAND_M = 0.1         # the camera gives no label this close to the split line
AGREE = (6, 8, 9)         # the fake brain's "N of 10" after its first, second and later fits
SESSION = "sim-lesson"


def sides(layout=LAYOUT):
    """((zone, (x, y)), (zone, (x, y))): where a person stands on the left, then on the right."""
    left, right = sorted(layout.centres)[:2]   # zones 1 and 2: either side of the split in both layouts
    return tuple((layout.zone_of(*layout.centres[z]), layout.centres[z]) for z in (left, right))


def stands(layout=LAYOUT):
    """[(from s, to s, zone)]: every stretch the person stands on one side, in order."""
    out, t, i = [], ARRIVE_S, 0
    while t + STAND_S <= END_S:
        if t + STAND_S > OUT_S and t < BACK_S:      # out of view: nobody is there
            t = BACK_S
            continue
        out.append((t, t + STAND_S, sides(layout)[i % 2][0]))
        t, i = t + STAND_S + MOVE_S, i + 1
    return out


def path(layout=LAYOUT) -> dict:
    spot = dict(sides(layout))
    person = [{"t": 0, "x": None}]
    for start, end, zone in stands(layout):
        x, y = spot[zone]
        if start == BACK_S:                          # they stepped out at OUT_S and are back now
            person += [{"t": OUT_S, "x": None}, {"t": BACK_S - 0.1, "x": None}]
        person += [{"t": start, "x": x, "y": y}, {"t": end, "x": x, "y": y}]
    return {"name": "lesson", "duration_s": END_S, "person": person,
            "about": "The lesson starts on an empty strip, the camera on the desk teaches left and right with a "
                     "step out of view in the middle, the model is fit, the camera is unplugged and the radio "
                     "carries on.",
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
