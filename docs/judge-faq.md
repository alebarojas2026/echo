# Echo: Twenty Hard Judge Questions

Each answer is two sentences. Speak the answer; offer source records or proof when asked.

## Isn't this just a laser tripwire?

Radio hidden in a bag or panel needs testing; we learn person versus thing and still versus moving. Compatible building Wi-Fi could avoid installing dedicated sensors; this desk line is one strand.

## Isn't presence just a signal-strength threshold?

For this spot, Wi-Fi attenuation provides the main presence decision and Bluetooth gives a second opinion. Learned patterns support person-versus-object and motion decisions, with the camera supplying temporary labels locally.

## How does the real kit work?

Walk between two devices and the Wi-Fi signal gives you away. The Arduino UNO Q and Pi A sit on the desk, with Pi B across one spot at desk height; the board computes locally.

## Does standing still make me disappear?

Most Wi-Fi sensing only sees movement; ours sees you standing still. Presence uses the sustained Wi-Fi change, while movement is a separate decision; its accuracy still needs held-out proof.

## Will it work on me or in another room?

People, furniture and radio paths differ, so the setup gets a local lesson. We have tested this desk arrangement, but another person or room needs independent validation rather than a promise of transfer.

## What about two people or someone passing behind me?

The demonstration is designed for one person in the spot, and intrusion waits for sustained presence. Multiple people and passers-by can disturb the signal, so their error rates remain unclaimed until measured.

## Why not CSI, radar or a motion sensor?

This board exposes signal strength rather than CSI, and radar needs dedicated sensing hardware. We want to reuse compatible building radios while reporting presence separately from movement.

## Why use a camera if you promise privacy?

The camera supplies temporary teaching labels and is unplugged before continued sensing. It saves no images, and the visible cable and teacher status let you check that boundary.

## Are you recording me?

The board records local radio summaries and events for replay, questions and reports, without identifying anyone. It stores no camera images and sends no sensing records to the internet during the local demo.

## What runs on the board and what needs the cloud?

Training, sensing decisions, alerts, records and answers run on the Arduino UNO Q's Qualcomm Dragonwing CPU. Neither Pi runs a model; the laptop and phone are local screens, and the live loop needs no cloud.

## How is a person different from a dead zone?

A person in the spot is never our dead-zone demonstration. It requires an object decision with nobody there and a weakened cross-gap Wi-Fi link; clearing the object or moving Pi B supplies the before-and-after test.

## Why not move the router to fix the link?

Pi A stays beside the cabled hub, so this kit cannot demonstrate a large router move. We clear the blocking object or move Pi B, then report only the measured change.

## Can I spoof it, jam it or unplug it?

A silent device while armed can raise a tamper alert, but that does not diagnose jamming. We do not claim defenses against spoofed radio data or deliberate interference.

## What happens when the board or a link fails?

A required link going blind pauses decisions, and a stale board feed makes the screens say No data. Neither means empty, and the board remains a single point of failure.

## How accurate is it, and how do I know it isn't scripted?

You can change the live signal by stepping into the spot, then inspect the source records. That demonstration is not held-out accuracy; every published result needs a method, sample size, date and commit in PROOF.md.

## Can the language model invent a replay or report?

Replay comes from saved summaries, with missing records shown as unknown. Ask selects relevant records and reports use their facts; inspect those rows if generated wording is unavailable or doubtful.

## What is the no-movement alert and how do I answer it?

The no-movement alert prompts a check when someone stays present and still; it does not diagnose the cause. Lean aside for the “I'm okay” check, wait for confirmation, and remember that a blind required link pauses the timer.

## What does it cost and how would it scale?

This prototype uses an Arduino UNO Q, two Raspberry Pis and a temporary teaching camera; we have no validated deployment price. The direction is local processing with compatible building radios, but building-wide coverage remains unmeasured.

## What did you write, and what came from libraries?

We wrote the radio pipeline, contracts, features, alert rules, records, local tools and interface. NumPy, scikit-learn, OpenCV, Three.js and Arduino App Bricks provide building blocks; the credits list libraries and the Wilson–Patwari research foundation.

## How does this fit Let's Dig In, and would you continue?

We dug into signal changes hidden beneath an ordinary connection indicator to find presence and blocked Wi-Fi. We would keep building it through repeatable tests across people, objects and room layouts before promising broader deployment.
