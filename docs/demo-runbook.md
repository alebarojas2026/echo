# Radio Sight Demo Runbook

Use this checklist for the live building-safety demo. It follows `CONTRACTS.md` v2. The desk round is the primary path; the finalist extension comes second. A result missing from `PROOF.md` stays `__`.

## Preflight

- [ ] Connect the UNO Q and Pi with the direct Ethernet cable.
- [ ] Ask Alexander to run `sudo bash pi/eth.sh` on the Pi and `sudo bash board/eth.sh` on the UNO Q.
- [ ] Ask Alexander to run `sudo bash pi/ap.sh` on the Pi and `sudo bash radio/wifi_join.sh` on the UNO Q.
- [ ] Join the demo laptop to the Pi's private hotspot. Do not copy files or bundles over it during a demo or recording.
- [ ] Open `http://192.168.77.2:8080/?src=ws` in the laptop browser.
- [ ] Confirm `/nodes.json` and `/proof.json` load from that address.
- [ ] Confirm `ws://192.168.77.2:8765/ws` produces contract v2 `state` messages.
- [ ] Confirm the source is `live`, the feed is fresh, and `health.status` is `ok`.
- [ ] Place every radio from `radio/nodes.json`; do not rely on remembered zone or node positions.
- [ ] Connect the temporary setup camera and confirm `cam-status` reports `on`.
- [ ] Clear people and movable objects from the sensing area before the baseline.
- [ ] Let the narrator warm its local model in the background. The template path remains available, so do not delay the demo.
- [ ] Confirm the proof strip renders JSON `null` as `__`.

Do not start while the screen says `NO DATA` or `SENSOR BLIND`. Neither state means the room is empty.

## Baseline and training

1. Set label mode to `off`, clear the sensing area, and start the baseline.
2. Wait for `baseline_done`; confirm every required link is healthy and health returns to `ok`.
3. Start a named training recording and set label mode to `person`.
4. Walk the configured zones while the camera teacher supplies zone and motion labels.
5. Stop recording, start training, and wait for the `trained` event.
6. Confirm `model.trained` is true and a radio prediction appears.

If a step fails, fix it and repeat the baseline or lesson. Do not carry failed calibration into the demo.

## Three-minute desk round

Use these exact beat names and keep them in this order. The words to say with each are in [pitch.md](pitch.md).

1. **Found you:** Start with the camera disconnected and the hall view behind the words. Ask the judge to step up to the desk. Show a fresh `person` prediction and say, “Found you. No camera is connected.” Do not substitute a numeric camera claim while proof remains pending.
2. **Live signal:** Point at the signal trace: it dipped when the judge stepped in. Ask the judge to wave a hand and let them see the line move. This is the answer to "is it scripted?".
3. **Teach the room:** Connect the camera, start the fresh judge lesson, and display `Lesson time: __ s`. The lesson starts with the space empty and has one step out of view; follow the words on screen. Show labels, not an image. Wait for successful training before continuing.
4. **Camera unplug:** Unplug the camera in one continuous shot. Follow the camera-unplug proof below and leave the cable visible.
5. **Still follows:** Ask the judge to step left, step right and then stand still. Show presence, side and motion state continuing from radio alone. If a required link goes blind, say so and stop; never call it empty.
6. **Arm the space:** Ask the judge to step out. Arm only when the screen shows nobody. Confirm contract v2 `armed` state and the `armed` event.
7. **Intrusion alert:** Ask the judge to step back in. Continue only after one live `intrusion` event names the side and the phone page shows it. Do not identify the judge or claim crowd counting.
8. **Tamper alert:** While still armed, ask Alexander to unplug the east beacon. Wait for the `tamper` event and the screen's plain words naming the device. Plug it back in and wait for `tamper_cleared` before the next beat.
9. **Ask the room:** Ask the prepared question. Read the returned facts and the rows under them; do not improvise an answer. If the reply says the tool was picked by rules, say so: the model was slow.
10. **Replay:** Press Replay next to the answer. Keep the replay banner on screen the whole time; a second with no record shows as "no record", never as an empty room. Return to live before the next beat.
11. **Incident report:** Disarm. Wait for the report card and read its text. Its numbers come from the board's records; do not add one.
12. **Proof:** Finish on `/proof.json`. Say only completed values. Close with `Images stored: __` and `Bytes sent outside local network: __` until proof records replace them.

### When the judge is short on time

Drop beats in this order: **Replay**, **Incident report**, **Tamper alert**, **Live signal** (leave the trace on screen), **Ask the room**, then **Arm the space** with **Intrusion alert**. Never drop **Found you**, **Teach the room**, **Camera unplug**, **Still follows** or **Proof**.

### Feature gates

Check each of these in preflight, on the real hardware, before the first judge:

- **Live signal:** the trace is on screen and dips when someone steps in.
- **Arm the space** and **Intrusion alert:** arming shows `armed`, stepping in sends one `intrusion`, and the phone page shows it.
- **Tamper alert:** unplugging the east beacon while armed sends `tamper`; plugging it back sends `tamper_cleared`.
- **Ask the room:** the prepared question gets an answer with rows, and `python -m store` is running.
- **Replay:** the answer has a Replay button and `GET /history` returns rows for it.
- **Incident report:** after a disarm, `GET /report` returns a report.

If a gate fails, skip that beat without comment. If the gate for **Arm the space** fails, stop the live sequence after **Still follows**. State that the remaining integrations are not ready, then go directly to **Proof**. Never stage an alert, an answer, a replay or a report.

## Camera-unplug proof

1. Keep the live laptop screen and camera cable visible together.
2. Unplug the camera without cutting away.
3. Confirm `cam-status` changes to `off` and `teacher` becomes null.
4. Confirm radio state continues to update and the source remains `live`.
5. Leave the camera unplugged for the rest of live sensing.

The camera supplies temporary setup labels. The demo must not show or save an image.

## Five-minute finalist round

Open with the whole-hall view and movement paths. Then run **Found you**, **Live signal**, **Teach the room**, **Camera unplug**, **Still follows**, **Arm the space**, **Intrusion alert**, **Tamper alert**, **Ask the room**, **Replay**, **Incident report**, and **Proof** in that same order.

After the primary path, use only the extensions that passed preflight:

- **No-movement alert and check-in:** Wait for the configured local alert, then use the practiced wave and confirm `checkin-toast` clears it.
- **Tray and router advice:** Ask Alexander to place the tray. Confirm `pi5>unoq:wifi` is dropping with `drop_db` of at least `3 dB`; advice does not appear without that live drop. Wait for `advice-text`, move only to a spot from `/nodes.json`, send `router_moved`, and report the before/after result only if proof contains it.
- **Recap:** Show the fact-based local recap. If generation is unavailable, use the template recap; never invent an event.
- **Game:** Invite interaction without saying the system counts or identifies the crowd.

## If asked

- The UNO Q performs local training and inference on its Dragonwing CPU. The Pi provides network and radio and runs no model.
- These development boards stand in for the radios or access points a building already has.
- The no-movement alert notices sustained stillness, not its cause.
- The dead-zone view reports which measured link something starts blocking. A full building coverage map is future work.

## Finish the live demo

Alexander handles the tray and Pi; the operator handles software controls.

1. If the tray was used, ask Alexander to remove it and wait for the object marker and static change to clear.
2. If the router moved, ask Alexander to return the Pi to its home spot, then send `router_home`.
3. After `router_home`, everyone steps away from the sensing area and its edge, including Alexander once the Pi is home, and stays out until a prediction returns or `baseline_done` appears.
4. Wait until prediction resumes or the automatic baseline finishes; confirm health is `ok`.
5. Disarm if needed, stop active recording, and send `reset`.
6. If the recap was used, keep the screen visible until the fact-based recap appears. The narrator warms its normal sentence prompt again in the background after the recap; do not hold the next judge for that warmup.

## Proof check

Open `/proof.json` and match each displayed value to the file:

- zone, presence, and person-versus-object results;
- training, decision, update, and no-movement timing;
- dead-zone improvement and power measurements;
- bytes out, images stored, and models on board; and
- measurement date, sample size, method, and commit.

A JSON `null` must render as `__`. Never replace it with an estimate. State the method and limits with each measured result.

## Recovery

### `NO DATA`

The last state is stale. Confirm the page loads, then check the WebSocket and sensing-model process. Do not describe the room as empty until fresh state resumes.

### `SENSOR BLIND`

A required classifier link is unhealthy. Check the named link, reader, and radio node. Predictions stay null, and alert and intrusion decisions pause until links recover.

### Camera or training failure

Reconnect the camera, confirm `cam-status` is `on`, and repeat the lesson. After successful training, camera `off` is expected; continue only if the live radio feed stays healthy.

### Armed or phone-page failure

Disarm, keep the judge outside the sensing area, and verify the live phone feed. If armed state, the `intrusion` event, or its phone card is missing, skip those beats rather than simulating them.

### Room-question failure

Do not answer from memory. Show the local event record if it is available, or state that the question feature is not ready and continue to **Proof**.

### Router move does not recover

Return the router to its home spot from `/nodes.json` and send `router_home`. Let the automatic baseline finish if the links do not recover.

### Narration is unavailable

Continue with the on-board template explanation. The narrator keeps warming locally after startup, a failed call, and the recap; never delay the demo or invent a description.

## After the demo

- [ ] Disarm and reset.
- [ ] Stop active recording.
- [ ] Save proof output with its method, sample size, date, and commit.
- [ ] Restore every node to its `/nodes.json` position.
- [ ] Confirm no image or video file was created.
- [ ] Keep every unmeasured public result as `__`.
