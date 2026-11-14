# Camera teacher

Only this app runs in App Lab. Import this directory, install the video object
detection brick, and set it as the default app. Disable camera preview. All pixels
stay in the brick's memory; this adapter handles boxes only.

Copy the mounted-camera calibration from `teacher/calib.json` to
`python/calib.json` (or set `TEACHER_CALIB`). The JSON contains `image_size`,
`side_m` and a 3 by 3 pixel-to-floor `homography`. Never use a sample calibration
on the board. Create a text `python/label_mode` containing `off`, `person` or
`object`; mount the host's mode file there or set `TEACHER_MODE_FILE` so the
controller can update it. A missing mode or calibration fails closed.

Labels go to UDP `msgpack-rpc-router:5600`, with one label per explicit processed
classification result, including an empty bounding-box list. No callback or an
absent boxes field is never interpreted as an empty room. Sequence and frame
counters advance together. Two people inside the square invalidate the label.

The brick's `on_detect_all` suppresses empty frames. The adapter therefore wraps
its `_process_message` boundary, before this filtering. This private interface
must be checked against the installed brick version during gate 3. The current
format is `classification.result.bounding_boxes`, each box carrying `label`,
`value`, `x`, `y`, `width`, `height` in pixels. No upstream code is copied.

On the mounted Brio, confirm the detector coordinate size matches calibration,
that callbacks arrive at 5–10 processed frames/s, that an empty frame increments
seq, and that stopping results never produces empty-room labels. Motion uses
the trailing 0.5 s coordinate median followed by displacement over a full second,
with a strict speed threshold of 0.25 m/s. Gaps over 0.5 s reset motion history.

Self-tests: `python -m pytest teacher/tests/test_labels.py`.
