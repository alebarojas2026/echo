# Desk view: the webcam on the desk, facing the strip

For the live lesson the webcam sits on the desk and looks at the person from close up. It sees a
torso, never feet, so there is no floor point and no corner clicking. The teacher only says
**nobody**, **left** or **right**, from where the person's box sits across the frame.

- One person, box centre clear of the split line: `present` true, `zone` 1 or 2, `foot_m` null,
  `motion` from how fast the box centre moves along the strip.
- Nobody in view: `present` false, `zone` 0.
- Someone in view but **standing back** (a box narrower than `near_width`): `present` false and
  `clipped` true, with `persons_in_frame` 1. They are behind the line of the arm beacons, where no
  link sees them, so the window is dropped. It is never `present` true: that would teach the radio
  that links nobody is touching can mean a person.
- `clipped` true (the window is left out of training) when the centre is inside the dead band
  around the split line, when the box is cut by the left or right edge of the frame, or when more
  than one person is in view. A box that runs off the top or bottom is normal here and is kept.

## One spot (a layout with one zone)

When `radio/nodes.json` has `frame.strip_m`, no `frame.zone_split_x_m` and exactly one zone, the
teacher only says **somebody** or **nobody**. There is no side and no line across the frame:

- One person in view, near enough: `present` true, `zone` the one zone, wherever the box sits
  across the frame. No dead band, so nothing is dropped in the middle.
- Standing back is handled exactly as above: `present` false, `clipped` true, until they step in.
- `clipped` is true only for a box cut by a side edge of the frame (unless `--keep-side-edge`) or
  more than one person in view.
- The file has `"zones": [1]` and no `split` or `dead_band`. `--cam-x-m` and `--dead-band` mean
  nothing here, and `TEACHER_DESK_SPLIT` and `TEACHER_DESK_DEAD_BAND` are ignored with a log line.
  The same two commands make it: `--desk`, then `--near`.

The floor view (clicked corners, foot points) is unchanged; which one runs depends only on the
calibration file the app is given.

## The file

On the board, with the desk layout's `radio/nodes.json` (it must have `frame.strip_m`, and either
`frame.zone_split_x_m` or one zone; the square is refused):

```sh
python -m teacher.calibrate --desk            # writes teacher/calib.json, numbers only
```

The split line, the strip's width and the two zone ids come from nodes.json. Options, all measured
on the desk, none assumed:

- `--cam-x-m X`: where the webcam sits along the strip, when it is not on the split line.
- `--view-m M`: how much of the strip the frame spans where people stand (two markers at the edges
  of the view, measured). It scales the split for an off-centre camera and the moving rule.
- `--dead-band F`: half the dropped band around the split, as a share of the frame width.
- `--no-mirror`: the camera looks the same way as the person. By default it faces them, so the
  person's left (zone 1, low x) is on the right of the frame.
- `--keep-side-edge`: keep a box cut by a side edge. Only if the person cannot step far enough
  without touching the edge; their centre is then further out than the box centre says, never nearer.

## How near is "in the strip": the two-step calibration

The desk file is not ready for a lesson until it has `near_width`: how wide a person's box is, as
a share of the frame width, when they stand in the strip. Without it the teacher labels nobody as
present (it does not guess a distance) and the preflight says `NOT READY FOR A LESSON`.

With the teacher app running and one person in view:

```sh
python -m teacher.calibrate --near --heartbeat <shared-directory>/heartbeat.json
```

1. The person stands at the desk edge, where a judge stands. Press Enter.
2. The same person takes one step back. Press Enter.

It reads the box width from the app's heartbeat (a number; no picture is read or kept), saves the
halfway point as `near_width`, and refuses if the two widths are too alike to tell apart. Then copy
the file to the app and restart it, as below. Redo it when the camera is moved or tilted.

To tune on the board without a new file, set any of `TEACHER_DESK_SPLIT`, `TEACHER_DESK_DEAD_BAND`,
`TEACHER_DESK_MIRROR` (1 or 0), `TEACHER_DESK_SIDE_EDGE` (clipped or keep) or `TEACHER_DESK_NEAR_WIDTH` for the app and restart it.

## Putting it on the board

Four files of the App Lab app are ours to copy (`python/labels.py`, `python/preflight.py`,
`python/heartbeat.py` and `python/main.py`); `app.yaml` is as it was. `$TEACHER_APP` is the app from the board's `.env`.

```sh
cp teacher/applab/python/labels.py teacher/applab/python/preflight.py \
   teacher/applab/python/heartbeat.py teacher/applab/python/main.py <the imported app>/python/
cp teacher/calib.json <the imported app>/python/calib.json
python -m teacher.preflight --calibration <the imported app>/python/calib.json \
  --mode-file <shared-directory>/label_mode --heartbeat <shared-directory>/heartbeat.json --box-size <WIDTHxHEIGHT>
arduino-app-cli app stop "$TEACHER_APP" && arduino-app-cli app start "$TEACHER_APP"
```

To go back to the floor view, copy the clicked calibration back over `python/calib.json` and restart.

## Check before a lesson

Watch the labels on the bus while one person stands left, right, on the line, one step back and
out of view. One step back must read `present` false and `clipped` true. The
zone must read 1 on the person's own left; if it reads 2, the picture is not mirrored the way the
file says: set `TEACHER_DESK_MIRROR=0` (or pass `--no-mirror`) and restart.

Tests: `python -m pytest teacher/tests/test_desk.py` (no camera, no board).
