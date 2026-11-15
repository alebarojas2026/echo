# Radio Sight: Spoken Pitch

Radio Sight brings safety and after-hours security to buildings using the Wi-Fi already there. The desk round below is the primary story. Keep the laptop interface and hardware visible, and do not say a proof value that is still `__`.

## Three-minute desk round

### Found you

_Start with the setup camera disconnected. Ask the judge to step into the sensing area._

> This is Radio Sight: Wi-Fi that understands the room. The radio links changed when you stepped in, so it found a person without identifying you. That decision was made on the Arduino UNO Q.

### Teach the room

_Connect the setup camera and start a fresh lesson on the judge._

> Buildings and people differ, so we teach the radio here. This temporary camera provides zone and motion labels for a short lesson. The Arduino UNO Q learns the radio pattern locally on its Qualcomm Dragonwing CPU. It saves no image.

### Camera unplug

_Unplug the camera in one continuous shot and keep the cable visible._

> The lesson is complete, and the camera is now unplugged. Its teacher status is off. From this point on, live sensing uses only the radio links around the room.

### Still follows

_Ask the judge to move, then stand still._

> Radio Sight still reports your presence, zone, and movement state. It does not need a clear view, and standing still does not make you disappear. A blind radio link produces no prediction, never a false all-clear.

### Arm the space

_Ask the judge to step out. Arm the room only when the armed-mode feature gate passes._

> Armed means this room should now be empty. Radio Sight keeps its learned room model on the board and watches for a new sustained person pattern.

### Intrusion alert

_Ask the judge to re-enter. Show the phone page only after it displays the live intrusion event._

> Your return creates one local intrusion alert for this entry. It names the zone, not the person. The phone is only another screen on our private network.

### Ask the room

_Use the prepared room question only when the local event-record feature gate passes._

> Now we can ask what just happened. The answer comes from the room's own timestamped records: it was armed, a person entered, and the intrusion alert fired. No cloud history is required.

### Proof

_Finish on the proof strip._

> Every measured result is on the proof screen with its method. Anything unmeasured is left out, not estimated. Radio Sight is taught by a camera, then runs without one.

## Five-minute finalist extension

Open with the whole-hall view and movement paths, then run the same eight beats in the same order. After **Proof**, add one or two of these only if the measured path is ready:

- show a no-movement alert and clear it with a deliberate check-in;
- place the tray, explain the person-versus-object result, and demonstrate router advice with measured before-and-after values;
- show the end-of-demo recap from recorded local events; or
- invite judges to try the crowd game, clearly labeled as a finalist interaction rather than a crowd-counting claim.

The Pi and optional beacons stand in for radios and access points already spread through a building. The product direction is to reuse that infrastructure, not to require this exact collection of development boards in every room.

## Feature gates

A beat is shown only after it passes preflight on the day. If a gate fails, skip that beat and close on **Proof**. Never stage a fake alert or answer.
