# Before starting the teacher

Inside the teacher container, set `TEACHER_CALIB`, `TEACHER_MODE_FILE`,
`TEACHER_HEARTBEAT` and `TEACHER_BOX_SIZE`. The last is `WIDTHxHEIGHT` in the
detector's bounding-box coordinate frame, not an assumed webcam resolution.
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
