# Radio Sight: Judge FAQ

## How does Radio Sight work?

Walk between two devices and the signal gives you away. Wi-Fi between the two Pis is the main sensor; Bluetooth to the Arduino UNO Q gives a second opinion. That same Wi-Fi link shows a dead zone.

## Why are there so many boards?

The three devices are the Arduino and two Pis, standing in for building radios. The UNO Q and Pi A sit together on the desk, with Pi B about a metre away at desk height.

## Why not just use a camera?

A camera captures identifying visual detail and needs a useful view of the space. Radio Sight uses one only as a temporary setup teacher, saves no image, unplugs it after the lesson, and continues from radio changes.

## Why not use a motion sensor or radar?

A basic motion sensor can stop reporting when a person stands still, while Radio Sight is designed to retain a learned presence state and distinguish it from movement. Radar can be effective, but it adds dedicated sensing hardware; our product direction is to reuse compatible building radios.

## Can it identify people or count a crowd?

It reports someone present and moving or still in one spot, without identity. It does not claim crowd counting, and a multi-person scene remains outside the measured scope.

## Does it work in any building?

With compatible radios and adequate link coverage, presence is the portable capability, but this prototype has been measured only in its current setup. Detailed zone and motion behavior needs a local lesson whose measured duration is still `__` seconds, plus validation in that room.

## What happens in a Wi-Fi dead spot?

Radio Sight can report the measured link that something starts blocking and show the change behind a weak area. A complete building coverage map is future work, so we do not turn one blocked-link result into a whole-floor claim.

## Why run it on-device?

Local training and inference keep the room's sensing loop available without a cloud service or venue internet. They also keep radio windows and event decisions on the UNO Q and private network; measured outbound bytes remain `__` until proof is complete.

## What runs on the Arduino UNO Q?

Model training and inference, signal-health checks, the radio X-ray, alert logic, advisor, narration, and local event decisions run on the UNO Q. Learned work runs on its Dragonwing CPU, and the Raspberry Pi runs no model.

## Why is there a Raspberry Pi too?

The Pi provides the private sensing hotspot, receives radio samples, and routes the laptop browser to the board. It is a network and radio participant while the UNO Q remains the computing hub for learned decisions.

## How do you protect privacy?

The system does not identify anyone, stores no camera images, and needs no cloud account for the live loop. The laptop and phone page are local displays, and images stored and bytes sent outside the local network remain `__` until the proof record supplies measured values.

## How accurate is it?

We will report held-out zone, presence, and person-versus-object results from sessions that were not used for training. Every result remains `__` until `PROOF.md` contains its method, sample size, date, and commit; a successful stage moment is not an accuracy study.

## What is the no-movement alert?

The timer runs only while the radio model reports a person present, still, and in the same enabled zone. It is a prompt to check on someone, not a diagnosis, and a blind required link pauses the timer rather than declaring the room empty.

## What can Radio Sight not do yet?

It cannot identify a person, count a crowd, reconstruct camera-like detail, or make a prediction while required links are blind. Armed-mode event logic is in `main`, but the live phone display and room-question integrations are not yet complete, and transfer to other rooms and full coverage mapping still need measured tests.

## Honest limits

- Radio patterns change with layout, interference, node placement, materials, and people, so calibration belongs to the deployment room.
- Person-versus-object behavior is limited to represented training patterns; an unfamiliar scene can be uncertain.
- Armed mode raises one intrusion event for a new sustained person appearance, but it does not identify who entered.
- Blind or stale input produces no prediction, not an “all clear.”
- Every public performance, timing, power, storage, and network result stays `__` until its proof record is complete.
