# Radio Sight: Spoken Pitch

Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras. The desk round below is the primary story. Keep the laptop interface and hardware visible, and do not say a proof value that is still `__`.

The beats below have the same names, in the same order, in [demo-runbook.md](demo-runbook.md), [devpost-draft.md](devpost-draft.md) and [video-shots.md](video-shots.md).

## Three-minute desk round

### Found you

_Start with the setup camera disconnected and the hall view behind the words. Ask the judge to step up to the desk._

> Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras. You stepped up and it found you. The laptop shows the local interface.

### Live signal

_Point at the signal trace as it dips. Ask the judge to wave a hand._

> These lines are the radio links on each side, live. Each shows that side's deepest drop. Wave your hand and they move. Nothing here is scripted.

### Teach the room

_Connect the setup camera and start a fresh lesson on the judge._

> Now a camera teaches the radio, for __ seconds. The Arduino UNO Q learns on its Dragonwing CPU. The Raspberry Pi supplies network and radio, but it runs no model. No image is saved.

### Camera unplug

_Unplug the camera in one continuous shot and keep the cable visible._

> The camera is unplugged, and it stays unplugged. Taught by a camera. Runs without one.

### Still follows

_Ask the judge to step left, step right, then stand still._

> It still follows you, left and right, even standing still. If a link goes blind it says so, never a false all-clear.

### Dead zone

_Put the tray at its marked spot. Wait for the advice, move Pi A to the named spot, and show the measured change._

> The same links find Wi-Fi dead zones. This tray blocked the router, the board told us where to move it, and the measured signal changed from __ to __.

### Arm the space

_Ask the judge to step out. Arm the space._

> Step out. Armed means this space should now be empty.

### Intrusion alert

_Ask the judge to step back in and stay put. Wait for the sustained-person rule, then show the live phone alert._

> Step back in and stay there. A passer-by gets no alert; a person who remains raises one intrusion alert, naming the side and never the person.

### Tamper alert

_Alexander unplugs the east beacon. Wait for the screen to name it._

> Now we unplug a beacon. It notices: a device went silent while armed. You cannot quietly switch it off.

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

> Measured: zone accuracy __, presence accuracy __, decision latency __, images stored __, and bytes sent outside our local network __. Blank means unmeasured, not estimated.

## When the judge is short on time

Drop beats in this order, and never drop **Found you**, **Camera unplug**, **Dead zone** or **Proof**. If the dead-zone path is unavailable, keep **Intrusion alert** instead:

1. **Replay**
2. **Incident report**
3. **Tamper alert**
4. **Live signal** (keep the trace on screen, skip the sentence)
5. **Ask the room**
6. **Arm the space** and **Intrusion alert**, together

## Five-minute finalist extension

Open with the whole-hall view and movement paths, then run the same beats in the same order. After **Proof**, add one or two of these only if the measured path is ready:

- show a no-movement alert and clear it with a deliberate check-in;
- explain the person-versus-object result behind the desk-round dead-zone advice;
- show the end-of-demo recap from recorded local events; or
- invite judges to try the crowd game, clearly labeled as a finalist interaction rather than a crowd-counting claim.

The Pi and optional beacons stand in for radios and access points already spread through a building. The product direction is to reuse that infrastructure, not to require this exact collection of development boards in every room.

## Feature gates

A beat is said only when it passed preflight on the day, on the real hardware. **Live signal**, **Tamper alert**, **Ask the room**, **Replay** and **Incident report** each have a line in the runbook's preflight. If a gate fails, skip that beat without comment; if **Arm the space** fails, stop after **Still follows** and close on **Proof**. Never stage a fake alert, answer, replay or report.
