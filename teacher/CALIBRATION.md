# Mounted-camera calibration

Stop the App Lab teacher before opening the Brio from the host. On the board
with a display, run `python -m teacher.calibrate --device /dev/video0`.
Install OpenCV on the host for this UI (`python3-opencv` on Debian).

During the build use loose markers at measured floor corners; tape is reserved
for the presentation hour. Click the corners in **SW, SE, NE, NW** order, as defined in
CONTRACTS.md, not relative to the camera view. Press Enter to accept, R to reset,
or Escape to cancel. The view remains in memory. The only output is
`teacher/calib.json`, containing pixel coordinates, image dimensions and a
pixel-to-floor homography. The area to click comes from `radio/nodes.json`. The
layout is moving to the desk layout: the strip a person stands in, in front of the
desk (`frame.strip_m`, split into two zones, Left and Right, at
`frame.zone_split_x_m`). The 2 x 2 m square with four zones is the old layout, and
is what a `nodes.json` without `strip_m` still gives. The tool prints which area
before the window opens. The strip's NE and NW corners are on the desk's judge
edge. `--side-m 1.5` overrides it with a 1.5 m square.

After saving, the tool prints `TEACHER_AREA=<width>x<height>` (metres). Set it in
the teacher app's environment: the App Lab container can't read `nodes.json`, so
this is how its preflight knows the layout's area. A calibration made for another
area, such as an old square one once the layout is the strip, is refused with a
message to recalibrate. On the host, `python -m teacher.preflight` takes the area
from `nodes.json` itself. `teacher/tests/test_strip.py` covers the strip, its
labels against the contract and this refusal, using the `strip` set in
`fixtures/boxes.json`.

Use the same camera resolution and detector coordinate frame during inference.
If the brick resizes or crops its boxes, calibrate in that coordinate frame;
do not silently reuse a full-resolution projection. Check every zone with
the mounted camera before recording training data. Copy the numeric calibration
into the App Lab app's Python directory, then restart the teacher. Recalibrate
after moving the camera. In the presentation room, tape the floor and redo
calibration, the 20 s baseline and training there. Do not commit a deployment's
calibration as a fixture.

`fixtures/boxes.json` is synthetic box geometry, with no images. Tests cover zone
boundaries, perspective and a scaled floor. Run `python -m pytest
teacher/tests/test_calibrate.py` without OpenCV, a camera or a board.
