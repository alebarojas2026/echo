# Host camera watcher

The board service runs `python -m teacher.camwatch` without flags and loads the
repository `.env` as its EnvironmentFile. Set `TEACHER_APP` to the installed App
Lab alias, `TEACHER_HEARTBEAT` to the host path of the mounted heartbeat file, and
optionally `TEACHER_DEVICE` to the Brio device path (default /dev/video0).
Flags override these environment values. The container's TEACHER_HEARTBEAT uses
the corresponding container mount path; it need not equal the host path string.
The Python entry point reads its process environment; systemd loads `.env`.

Run `python -m teacher.camwatch --app user:radio-sight-teacher --heartbeat
<host-shared-directory>/heartbeat.json` on the **host**, not inside App Lab.
Use the installed app's actual alias and the Brio's stable video-device path
with `--device`; keep local identifiers out of the repository.

Mount a host directory into the teacher container and set `TEACHER_HEARTBEAT`
to `heartbeat.json` inside that mount. The app atomically replaces this file
after each processed label. It contains only an epoch timestamp and frame
counter. Mount the directory rather than the file so atomic replacement works.
Set `TEACHER_MODE_FILE` to the controller's mounted label-mode text file too.
Neither file contains pixels. No new network port or message format is added.

The watcher polls USB-device presence every 50 ms. It stops the App Lab app on
unplug, waits 2 s after replug before starting, and emits `cam` messages to
`127.0.0.1:5600` on every state change and at least once per second. It reports
`stalled` while the device exists but has produced no fresh result for 1 s;
`off` means the device is absent. A heartbeat from before replug cannot mark
the camera on. FPS comes from frame-counter and timestamp deltas, not timers.

App start/stop uses `arduino-app-cli app start/stop <app>` on a worker thread;
errors retry three times and are logged. A running lifecycle command may delay
a subsequent one, but cannot block camera-state messages. The host service user
must have permission to manage that app and read the shared directory.

Needs the board: confirm the Brio's device path, mount permissions, CLI alias,
unplug/replug, frame stalls and 5–10 Hz operation. Self-tests inject USB states,
frame counters and CLI execution: `python -m pytest teacher/tests`.
