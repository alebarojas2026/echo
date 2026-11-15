# Radio Sight: Three-Minute Video Shot List

The Devpost video, three minutes at most. The beats have the same names, in the same order, as [pitch.md](pitch.md) and [demo-runbook.md](demo-runbook.md).

**Where the footage comes from**

- **Screen:** a screen capture of the live system in the laptop browser. The laptop shows the local interface; never a mock or the simulator.
- **Desk:** a phone filming the desk, the strip in front of it and the hardware, in one fixed frame.
- **Hall:** the rendered fly-in through the hall model. It exists as video files outside the repo.

**Two rules for every shot**

- No face that can be identified. Film from the shoulders down or from behind, and frame the desk shot so heads are out of it.
- No number that is not in PROOF.md. A value that is still pending is shown and said as `__`.

## 0:00–0:10 — Opening

**Source:** Hall.

**Picture:** The fly-in through the hall, ending above the desk. Nobody is at the desk.

**Voiceover:** "Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras."

**On screen:** `Radio Sight · safety and after-hours security · no cameras`

## 0:10–0:22 — Found you

**Source:** Desk, then Screen.

**Picture:** A person steps up to the desk, seen from behind. Cut to the screen as the figure appears on that side. The camera cable lies unplugged in the shot.

**Voiceover:** "Step up, and it finds you. No camera is connected. Everything runs on an Arduino UNO Q, on its Dragonwing CPU."

**On screen:** `Found you · camera: off`

## 0:22–0:32 — Live signal

**Source:** Screen, with the Desk shot inset.

**Picture:** The two side traces dip as the person steps in. A hand waves in the desk shot and the lines move with it.

**Voiceover:** "These lines are the radio links on each side, live. Each shows that side's deepest drop."

**On screen:** `Left and Right radio links · live`

## 0:32–0:52 — Teach the room

**Source:** Desk, then Screen.

**Picture:** A hand plugs in the webcam. On the screen the lesson runs: empty, left, right, a step out, left, right. Only labels are shown, never the camera's picture.

**Voiceover:** "A camera teaches the radio what left, right and nobody look like. The lesson takes __ seconds, on the board. No image is saved."

**On screen:** `Lesson time: __ s · images stored: __`

## 0:52–1:00 — Camera unplug

**Source:** Desk, one unbroken shot.

**Picture:** The hand unplugs the webcam and lays the cable down in view. The screen behind it keeps updating.

**Voiceover:** "Then the camera is unplugged. Taught by a camera. Runs without one."

**On screen:** `Camera: off · Radio: live`

## 1:00–1:12 — Still follows

**Source:** Screen, with the Desk shot inset.

**Picture:** The person steps left, steps right, then stands still. The figure follows and the state reads still.

**Voiceover:** "It still follows them, left and right, even standing still."

**On screen:** `Person · Still · Right`

## 1:12–1:32 — Dead zone

**Source:** Desk, then Screen.

**Picture:** Put the tray at its marked spot. Hold on `Dead zone found` and the named router move, then slide Pi A to that spot and show the before and after values.

**Voiceover:** "The same links find Wi-Fi dead zones. The board says where to move the router, then measures the change."

**On screen:** `Dead zone found · Before: __ · After: __`

## 1:32–1:39 — Arm the space

**Source:** Screen.

**Picture:** The person has stepped out. The operator arms the space and the screen shows armed, nobody here.

**Voiceover:** "After hours, the space is armed: it should be empty."

**On screen:** `Armed`

## 1:39–1:53 — Intrusion alert

**Source:** Desk, then a phone screen.

**Picture:** The person steps back in, stays put through the sustained-person wait, then the phone page shows the alert.

**Voiceover:** "A passer-by gets no alert. Someone who steps in and stays raises one, naming the side, never the person."

**On screen:** `Intrusion alert · Left`

## 1:53–2:03 — Tamper alert

**Source:** Desk, then Screen.

**Picture:** A hand unplugs the east beacon. The screen names the device in the fault colour.

**Voiceover:** "Unplug a device, and it notices. You cannot quietly switch it off."

**On screen:** `East beacon unplugged while armed`

## 2:03–2:15 — Ask the room

**Source:** Screen.

**Picture:** The question is typed. The answer appears with the records it came from under it.

**Voiceover:** "Ask what happened. The board works out which records the question is about, then fills the answer from them."

**On screen:** `Answered on the board`

## 2:15–2:25 — Replay

**Source:** Screen.

**Picture:** Replay is pressed. The figure replays the last minute under the replay banner, then the screen returns to live.

**Voiceover:** "And replay it. No video: only what the radio decided, once a second."

**On screen:** `REPLAY · from the board's records`

## 2:25–2:33 — Incident report

**Source:** Screen.

**Picture:** The space is disarmed and the report card appears. Hold on its text.

**Voiceover:** "Disarm, and the board writes the incident report from its own records."

**On screen:** `Incident report · written on the board`

## 2:33–2:55 — Proof

**Source:** Screen, with the unplugged camera cable at the edge of the Desk shot.

**Picture:** The proof strip fills the frame. Use only values loaded from the measured proof report.

**Voiceover:** "What we measured: zone accuracy __, decision latency __, images stored __, and bytes sent outside our local network __."

**On screen:**

- `Zone accuracy: __`
- `Presence accuracy: __`
- `Decision latency: __`
- `Images stored: __`
- `Bytes sent outside local network: __`

## 2:55–3:00 — Close

**Source:** Desk.

**Picture:** The hardware and the live screen together, nobody in frame.

**Voiceover:** "Radio Sight. Taught by a camera. Runs without one."

**On screen:** `Radio Sight · MadHacks 2026 · Qualcomm / N+1`

## Capture notes

- Film the camera unplug and the beacon unplug without a cut, with the screen in the same frame.
- Record the screen from the live system on the real hardware. If a beat has not passed preflight, leave its shot out and close the gap; never fill it with a mock.
- Replace every `__` only with a value produced by the proof workflow, on screen and in the voiceover.
- Check every shot for a face before it goes in. Reshoot or crop instead of blurring.
- Do not add a claim that the recorded demo and proof data do not support.
