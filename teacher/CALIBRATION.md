# Mounted-camera calibration

Stop the App Lab teacher before opening the Brio from the host. On the board
with a display, run `python -m teacher.calibrate --device /dev/video0`.
Install OpenCV on the host for this UI (`python3-opencv` on Debian).

During the build use loose markers at measured floor corners; tape is reserved
for the presentation hour. Click the corners in **SW, SE, NE, NW** order, as defined in
CONTRACTS.md, not relative to the camera view. Press Enter to accept, R to reset,
or Escape to cancel. The view remains in memory. The only output is
`teacher/calib.json`, containing pixel coordinates, image dimensions and a
pixel-to-floor homography. The area to click comes from `radio/nodes.json`: the
2 x 2 m square today, and on the desk layout the strip a person stands in
(`frame.strip_m`, split into two zones at `frame.zone_split_x_m`); the tool prints
which before the window opens. The strip's NE and NW corners are on the desk's
judge edge. `--side-m 1.5` overrides it with a 1.5 m square.

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

## Desk mode (the desk layout)

With the webcam on the desk facing the strip, the teacher only needs left or right. No clicks and no
floor projection: run

```
python -m teacher.calibrate --desk --image-size 640x480 --split-u <column> --u-range <west-or-east end> <other end> --left-zone 2
```

with the detector's box frame size, the pixel column where the zone split line falls, the columns of
the strip's two ends, and the zone on the image's left (2 when the camera looks out at the aisle:
east is on its left). It needs the strip in `radio/nodes.json`. A person counts by the centre of
their box, so feet don't need to be in view; a box cut by the image's left or right side is
clipped. `foot_m` is null in desk mode. Tests: `python -m pytest teacher/tests/test_desk.py`.
