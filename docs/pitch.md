# Radio Sight: Spoken Pitch

Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras. The desk round below is the primary story. Keep the laptop interface and hardware visible, and do not say a proof value that is still `__`.

The beats below have the same names, in the same order, in [demo-runbook.md](demo-runbook.md), [devpost-draft.md](devpost-draft.md) and [video-shots.md](video-shots.md).

## Three-minute desk round

### Found you

_Start with the setup camera disconnected and the hall view behind the words. Ask the judge to step up to the desk._

> Walk between two devices and the signal gives you away. Radio Sight found someone in this spot without identifying you. That decision was made on the Arduino UNO Q.

### Teach the room

_Connect the setup camera and start a fresh lesson on the judge._

> Buildings and people differ, so we teach the radio here. A temporary camera labels presence and motion for a short lesson. The Arduino UNO Q learns locally on its Qualcomm Dragonwing CPU. It saves no image.

### Camera unplug

_Unplug the camera in one continuous shot and keep the cable visible._

> The camera is unplugged, and it stays unplugged. Taught by a camera. Runs without one.

### Still follows

_Ask the judge to step left, step right, then stand still._

> Most Wi-Fi sensing only sees movement. Ours sees you standing still. Wi-Fi across this gap is our main sensor. Bluetooth gives a second opinion. The same Wi-Fi link shows a dead zone.

### Arm the space

_Ask the judge to step out. Arm the space._

> Step out. Armed means this space should now be empty.

### Intrusion alert

_Ask the judge to step back in and stay put. Wait for the sustained-person rule, then show the live phone alert._

> Step in and stay here. Once the board confirms the sustained presence, the phone shows the intrusion alert. It reports someone in this spot without identifying them.

### Ask the room

_Type or pick the prepared question._

> Ask it what happened. The board works out which records the question is about, and fills the answer from those records.

### Replay

_Press Replay next to the answer. Leave the replay banner visible._

> Press Replay. This is what the room recorded: no video, only what the radio decided, once a second.

### Incident report

_Disarm. Wait for the report card._

> Disarm, and the board writes the incident report: when it was armed, each alert, and how long someone was here.

### Proof

_Finish on the proof strip._

> Every measured result is on the proof screen with its method. Anything unmeasured is left out, not estimated. Radio Sight is taught by a camera, then runs without one.

## Five-minute finalist extension

Run the same one-spot demo with the Arduino and two Pis. After **Proof**, add one or two of these only if the measured path is ready:

- show a no-movement alert, ask the judge to lean aside for the “I'm okay” check, and wait for the check-in confirmation;
- place the tray, explain the person-versus-object result, and demonstrate router advice with measured before-and-after values;
- show the end-of-demo recap from recorded local events; or
- invite judges to try the crowd game, clearly labeled as a finalist interaction rather than a crowd-counting claim.

The three devices are the Arduino UNO Q and two Pis. The UNO Q and Pi A sit on the desk; Pi B sits about a metre away at desk height. They stand in for radios and access points already in a building. This kit detects one spot.

## Feature gates

A beat is shown only after it passes preflight on the day. If a gate fails, skip that beat and close on **Proof**. Never stage a fake alert or answer.
