# Radio Sight: Judge FAQ

## How does Radio Sight work?

Radio Sight reads changes in Wi-Fi and Bluetooth signal strength across links around the room. A model on the Arduino UNO Q's Dragonwing CPU turns those patterns into presence, movement, zone, and person-versus-object predictions, while link health prevents a broken sensor from being mistaken for an empty room.

## What does it show during the demo?

The screen shows a radio X-ray, the strongest changed links, the predicted zone and motion, and whether a change looks like a person or an object. It also recognizes a practiced wave as a check-in and can recommend a tested router position when an object creates a dead zone.

## Why not just use a camera?

A camera needs a clear view and collects much richer information than this task requires. Radio Sight uses a camera only as a temporary teacher during setup, then unplugs it and continues live sensing from radio changes without saving images.

## What runs on the Arduino UNO Q?

All model training and inference, signal health checks, the radio X-ray, check-in logic, no-movement alert logic, advisor, and narration run locally on the UNO Q. The learned work runs on the Dragonwing CPU, and the system does not depend on a cloud service.

## Why is there a Raspberry Pi too?

The Pi provides the private sensing hotspot, receives radio samples, and routes the laptop browser to the board. It runs no model; the UNO Q remains the computing hub for every learned decision.

## How do you protect privacy?

The system stays on its own local network and does not need venue Wi-Fi or a cloud account. It stores no camera images, does not identify anyone, and reports measured outbound bytes as `__` until the proof run supplies a value.

## How does it tell a person from an object?

During training, temporary camera labels pair radio patterns with a person or a known object while clipped and unlabeled windows are rejected. During live use, the model combines those learned patterns with motion and stability rules, but it does not identify the person or name an unknown object.

## What happens if furniture moves?

A new obstruction appears as change since the baseline, and a stable change near the router can trigger placement advice. A major room-layout change can invalidate the learned reference, so we clear the room and run a new baseline or retrain instead of pretending the old calibration still applies.

## How accurate is it?

We report held-out results from separate recorded sessions, including zone accuracy, confidence, and person-versus-object accuracy. Those results remain `__` until the matching proof data is measured; we do not turn a live demo success into an accuracy claim.

## What is the no-movement alert?

In a configured zone, the timer counts only while the radio model says a person is present, still, and in the same zone. A check-in or reset clears the alert, and a blind radio link pauses it; it is a prompt to check on someone, not a medical or emergency claim.

## Does the system need the camera after setup?

No: the camera supplies zone and motion labels for baseline and training, then it can be unplugged for the radio-only demo. A new room or a deliberate retraining session needs the setup teacher again so the model has honest ground truth.

## What can Radio Sight not do?

It cannot identify people, reconstruct camera-like detail, or make a prediction when required radio links are blind. It is calibrated to one room and layout, so it does not claim that a model trained here will work unchanged somewhere else.

## Honest limits

- Radio patterns change with room layout, interference, node placement, and people, so calibration belongs to the room where the system runs.
- The person-versus-object result is limited to the patterns represented in training; an unfamiliar scene can be uncertain.
- A blind classifier link produces no prediction, not an "empty" result, and no-movement alert timers pause until health recovers.
- Predictions pause while the router is away from its home position and while recalibration is running.
- Every public performance, timing, power, and network result stays `__` until its proof record is complete.
