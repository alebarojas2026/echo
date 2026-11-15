# Echo

**A witness that never watches. Echo knows when someone is in a space, keeps a record nobody can edit, and tells you what happened. No camera, no microphone, no cloud.**

## Inspiration

Some places need a record of who was there and when, and cannot have cameras: server rooms and network cabinets, evidence rooms, labs after hours, restrooms, hotel rooms. A camera is too much in those places, and a log that someone can quietly edit is not enough.

We wanted a witness that can't see you, can't be edited, and still tells you exactly what happened. We built Echo at MadHacks 2026 for the Qualcomm / N+1 Institute track and the theme "Let's Dig In": we dug into what an ordinary Wi-Fi signal already knows about the space it crosses.

## What it does

The demonstration has six beats:

- **Found you:** two small computers sit a metre apart. A body between them weakens the Wi-Fi signal. From that one line the board knows someone arrived, how long they stayed, whether they are standing still or moving, and when they left.
- **Intrusion alert:** armed, the spot should be empty. Step in and stay, and the board raises an intrusion alert on a phone page.
- **Tamper alert:** unplug one of Echo's own devices and it says which one went quiet. The others carry on, and the gap itself is recorded.
- **What happened:** every second, and every event, is a record on the board. Ask "What happened?" and a program on the board answers in plain words from the sealed record only, showing its steps and the records it used.
- **Engine room:** a second screen shows the three devices, the record counting up, the signatures arriving and a prove-it check. The check changes one record in a copy, verifies the copy and names the record that broke the seal. The real record is never touched.
- **Proof:** the measured results below, each with its count and range.

**It seals what it sensed.** Each record carries the SHA-256 hash of the one before it, so a changed record breaks every seal after it and the board can name the record that was changed.

**Two more machines vouch for it.** Each Raspberry Pi signs the board's latest record every five seconds with its own Ed25519 key.

### What it does not do

Echo does not know who a person is, and it does not know which part of a room they are in. It senses one spot. A person needs a few seconds on the line to be found. There is no camera and no microphone on the kit.

### Proof

One person, one night, replayed from recordings taken on the kit. The recordings were split into a tuning set and a held-out set before the settings were chosen, and these numbers come from the held-out set only. Each has its method in PROOF.md in our repository.

- One person stood on the spot for ten seconds, ten times, and Echo found them 10 of 10 times; with this few trials the true rate is probably between 69% and 100%.
- Five of those ten stands were with the second device hidden in a backpack, and it found 5 of 5; with this few trials the true rate is probably between 47% and 100%.
- With nobody on the spot it said somebody 0 times in 9.4 empty minutes; with this little time the true rate is probably under 0.4 a minute.
- Once the signal dropped, the decision came 0.50 to 0.58 seconds later; that leaves out the time a person takes to step in, which we did not record.
- In one session of standing still, 167 of 170 decisions said still, and in one session of stepping about, 154 of 170 said moving: one session each, so it shows it can work, not how often. Every miss was in the first seconds: the word takes about 3 to 5 seconds to change.
- With the second device low on a chair seat it found 0 of 5 stands. That is a limit: the device has to be at about desk height.
- Only the Wi-Fi line decides: in the open a person took 11 to 24 dB off it and the empty line dipped 2 dB at most, while the Bluetooth lines dipped 7 to 14.5 dB with nobody there.
- Those numbers are one spot, one person and one night, replayed from recordings taken on the kit. In one run with the board deciding by itself at the time, it said an arrival for 10 of 10 stands and none in the two empty minutes after.

## How we built it

Everything runs on an Arduino UNO Q (Qualcomm Dragonwing QRB2210): the sensing decision, the records, the checking and a small language model, all on the Dragonwing CPU. Neither Pi runs a model. Echo needs no internet connection and calls no cloud service.

1. **Reading.** Pi A is a 5 GHz Wi-Fi hotspot. Pi B, a metre away at desk height, measures how strong that signal is 25 times a second and sends the readings to the board.
2. **Decision.** The board compares each second with the level of the empty spot. A drop that holds is a person; how steady it is says still or moving; how long it lasts says how long they stayed. There is no trained model in this step: after a baseline with the spot empty, the line alone gives the decision.
3. **Record.** The board writes one summary a second, plus one record for every event, to a small database on the board.
4. **Seal.** Each record carries the SHA-256 hash of the record before it.
5. **Signature.** Every five seconds each Pi signs the newest hash with its own key. The private keys are made on each Pi and never leave it.
6. **Answer.** "What happened?" is answered from the sealed records in the stretch asked about, with clock times and record numbers.

The screens are browsers on the kit's own Wi-Fi: the judge's page with a 3D room and a faceless figure, the engine room, and the alarm page on a phone.

In this demo our own boards stand in for what a building already has. Pi A stands in for an access point, Pi B for a device across the room, and the UNO Q for the chip that would run this inside the access point. One desk stands in for a room.

## Challenges

We started with a bigger design: several radio links, a model taught from labels, and areas along a desk. The real kit taught us otherwise. Measured on the hardware, only the Wi-Fi line across the gap separated a person from an empty spot; the other radio lines moved as much with nobody there. We cut everything else and rebuilt around the one line that worked.

A build that passed every simulated test failed on the board in its first minute, because no test had started the real programs cold. After that, every build had to pass a cold start with real recordings before it went on the board.

Placement matters more than we expected. With the second device low on a chair seat the system found nobody, so the device has to sit at about desk height. A person crossing the line quickly is too brief to rely on, so we do not claim it.

## Accomplishments

Echo makes its whole decision from one ordinary Wi-Fi signal, with no camera, no microphone and no trained model, on a single Arduino UNO Q.

The record is hard to fake: to change one entry, someone would have to redo every seal after it and forge signatures from two keys that live on two other machines.

We only say what we measured. Every number above has a method, a count and a range behind it, and the limits are written next to the results.

## What we learned

One good signal beats several weak ones. Measuring each radio line on the real kit, before building on it, changed the whole design.

A record is only worth trusting if it can show it has not been edited. Sealing and signing turned a sensing demo into something that can act as a witness.

Honest limits are part of the product. "It senses one spot and does not know who" is a more useful sentence than a claim we could not defend.

## What's next

More people, more nights and more rooms, so the ranges on our numbers get narrower. Then live measurements on the board itself for every result, not replays, including a measured count of the bytes the board sends outside its own network.

After that, running the same idea on the Wi-Fi a building already has: an access point and the devices already connected to it, with no extra hardware in the room.

## Images

This is the capture and caption plan for the submission lead. Take every view from the live desk, never the simulated demo. Include no recognisable face. Keep photos, clips, and the exported diagram outside the repository; commit only this plan.

| Demo order | Image to capture | Caption |
|---|---|---|
| 1. Cover | The main laptop with the figure on the spot, and the three devices in the same view | The Arduino UNO Q knows someone is on the spot from one Wi-Fi line, with nothing watching. |
| 2. Found you | The headline and the still or moving word on the main laptop | The Arduino UNO Q finds a person standing between Pi A and Pi B. |
| 3. Intrusion alert | The alarm page showing the live intrusion beside the main laptop | The Arduino UNO Q raises an intrusion alert when someone stays on the armed spot. |
| 4. Tamper alert | Pi B's cable in a hand, with the tamper alert on screen | The Arduino UNO Q names the device that went quiet and records the gap. |
| 5. What happened | The answer with its steps and cited records | The Arduino UNO Q answers "What happened?" from its sealed record only. |
| 6. Engine room | The second laptop: the record counting, the signatures, the Prove it result | The Arduino UNO Q's record is sealed, signed by both Pis and checked on screen. |
| 7. The hardware | Label the Arduino UNO Q and Pi A together on the desk; label Pi B across the gap at desk height | The Arduino UNO Q does all the work; Pi A makes the Wi-Fi signal and Pi B measures it. |
| 8. Architecture | Export the current diagram once for Devpost, outside the repository | The Arduino UNO Q senses, seals, checks and answers with no cloud service. |

Use the current diagram from docs/architecture.md. The layout has one spot and three devices. The capture lead must check that each caption matches the deployed build before uploading.

## Built with

- Arduino UNO Q and Qualcomm Dragonwing
- Raspberry Pi 5
- Python, SQLite, and WebSockets
- SHA-256 and Ed25519 signatures with OpenSSL
- llama.cpp for the small on-board language model
- Three.js, TypeScript, Vite, Vitest, and Playwright

## Team

- **Ivan:** team lead; message contracts, the screens, the sealed record and the witnesses
- **Alexander:** hardware, radio links, the Pis and board bring-up
- **Izet:** the on-board decision and the proof measurements
- **Alejandro:** simulation and rehearsal tools, the first on-board record store and question answering, docs
