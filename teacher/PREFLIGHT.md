# Before starting the teacher

Inside the teacher container, set `TEACHER_CALIB`, `TEACHER_MODE_FILE`,
`TEACHER_HEARTBEAT` and `TEACHER_BOX_SIZE`. The last is `WIDTHxHEIGHT` in the
detector's bounding-box coordinate frame, not an assumed webcam resolution.
Also set `TEACHER_AREA`, the layout's area as `WIDTHxHEIGHT` metres, printed by
`python -m teacher.calibrate`; a calibration for another area (an old square one
once the layout is the strip) is refused with a message to recalibrate. The host
command below reads the area from `radio/nodes.json` unless `--area` is given.
Read it from the installed model's configuration and confirm on the board.
The app runs numeric preflight before importing or constructing the brick.

The same checks run without a camera or the Arduino package:

```sh
python -m teacher.preflight --calibration teacher/calib.json \
  --mode-file <shared-directory>/label_mode \
  --heartbeat <shared-directory>/heartbeat.json --box-size <WIDTHxHEIGHT>
```

Run inside the container as well as on the host, using the corresponding mounted
paths. The check rejects non-finite or singular projections, mismatched detector
dimensions, inconsistent floor corners, missing/invalid mode files and an
unwritable heartbeat directory. The permission probe contains numeric text and
leaves no file behind. It does not claim the camera or UDP bus is working.

Use measured loose markers during the build. Alexander tapes the presentation
layout during the presentation hour, then repeats calibration, the 20 s baseline
and training in that room. Do not reuse a different room's calibration.

With the desk view (teacher/DESK.md) the calibration file holds the split line, dead band and
mirroring instead of corners; the same command checks it.
