# Radio Sight Demo Runbook

Use this checklist for the live building-safety demo. It follows `CONTRACTS.md` v2. The desk round is the primary path; the finalist extension comes second. A result missing from `PROOF.md` stays `__`.

## At the desk

| Role | Name | Does | Never |
|---|---|---|---|
| Talker | __ | Says the round, hands over the camera cable and phone | Touches the laptop |
| Operator | __ | Drives the laptop: arm, reset between judges, and Ask | Explains while typing |
| Hardware | __ | Handles the Arduino, two Pis, camera hand-off, and anything knocked | Leaves the desk |
| Spotter | __ | Keeps the aisle behind the judge clear and places a second judge | Blocks the sensing strip |

Keep at least two people at the desk for every half hour:

| Time | Person | Person |
|---|---|---|
| 1:00–1:30 PM | __ | __ |
| 1:30–2:00 PM | __ | __ |
| 2:00–2:30 PM | __ | __ |
| 2:30–3:00 PM | __ | __ |

The Hardware role answers radio and hardware questions. The Operator answers model and proof-number questions. The Talker answers cost and what's next.

While the Operator fixes a failure, the Talker says exactly one of these:

- **Sensor blind:** “That's the honest failure. A radio link dropped, so it says blind instead of guessing the room is empty. Give us ten seconds.”
- **No data:** “The screen lost the board's feed, so it says no data, not empty. Reconnecting.”
- **The lesson fails:** “The lesson needs a moment with nobody in view. Step out for three seconds and back in.” If it fails twice: “We'll use the lesson it learned this morning.”
- **Ask the room is slow or wrong:** “The language model on this board is tiny. The records it reads from are right; here they are.” Press Replay.
- **The board will not return in 30 s:** “This is a recording of the real board from this morning.” Play the time-titled recording kept on the demo laptop, never the simulated demo.

## Preflight

### Before the first judge

Record the operator, checker, and actual finish time beside each step. These are scheduling blanks, not performance results.

| Order | Action | Time | Operator / checker |
|---|---|---|---|
| 1 | Power up the Arduino UNO Q, Pi A, Pi B, and laptop | __ | __ |
| 2 | Set the board's clock from the laptop using the operator clock control; disarm and stop recordings first, then wait for reconnection | __ | __ |
| 3 | Run `python scripts/demo_check.py --before-lesson`; fix every FAIL using its printed instruction | __ | __ |
| 4 | Write down the commit the deploy printed and the served screen build: board __, screen __, previous good tag __ | __ | __ |
| 5 | Capture the empty baseline | __ | __ |
| 6 | Run the morning lesson and confirm the model is trained | __ | __ |
| 7 | Have someone outside the team walk the full round | __ | __ |
| 8 | Ask one prepared question using the real local model and inspect its source records | __ | __ |
| 9 | Copy what the board learned to the laptop over Ethernet, using the backup procedure once #679 lands | __ | __ |

Run `python scripts/demo_check.py` again after the lesson. A FAIL is a stop: page/layout means check the web server and deployed layout; WebSocket means check bus and brain; clock means set time while idle; links/health means inspect the named radio; model means baseline and lesson; records means check `radio-sight-store`; Ask means inspect the answer service and local model. A degraded-health WARN still has predictions; inspect the named device without calling it empty.

**From Sunday 9:30 AM the board runs a tagged commit. Nothing goes onto it afterwards except a rollback to the previous tag: no deploy or screen build pushed during judging.**

**Before any restart, save the logs: `journalctl -u 'radio-sight-*' --since -5min > incident-<time>.txt`. Replace `<time>` with the actual incident time in the local filename.**

### Going back

Record last good board tag __, last good screen build __, operator __, checker __, and measured recovery time __ s. Save the logs first. The recovery sequence from #678 is:

1. `board/deploy.sh <last-good-tag>` — use the recorded previous tag, already available locally.
2. `board/push-web.sh --back` — restore the previous screen build locally on the board.
3. `python scripts/demo_check.py` — inspect the screen and every check before admitting another judge.

The screen `--back` option and `board/keep.sh save` backup are pending #678 and #679 in this checkout. Confirm they exist in the deployed version and have passed a real restore before using this checklist as a recovery guarantee. Never rebuild or copy a screen bundle over the hotspot while the model runs.

- [ ] Connect the UNO Q and Pi with the direct Ethernet cable.
- [ ] Ask Alexander to run `sudo bash pi/eth.sh` on the Pi and `sudo bash board/eth.sh` on the UNO Q.
- [ ] Ask Alexander to run `sudo bash pi/ap.sh` on the Pi and `sudo bash radio/wifi_join.sh` on the UNO Q.
- [ ] Join the demo laptop to the Pi's private hotspot. Do not copy files or bundles over it during a demo or recording.
- [ ] Open `http://192.168.77.2:8080/?src=ws` in the laptop browser.
- [ ] Confirm `/nodes.json` and `/proof.json` load from that address.
- [ ] Confirm `ws://192.168.77.2:8765/ws` produces contract v2 `state` messages.
- [ ] Confirm the source is `live`, the feed is fresh, and `health.status` is `ok`.
- [ ] Power Pi B, join it to Pi A's hotspot, and confirm its reader sends through Pi A to the board.
- [ ] Set the three devices for one spot: Arduino UNO Q and Pi A together on the desk, Pi B about a metre away at desk height on a chair. Confirm the deployed `radio/nodes.json` matches this kit.
- [ ] Keep the path between Pi B and the desk clear. Wi-Fi from Pi A to Pi B is the main presence sensor and the dead-zone link; Bluetooth from Pi B to the board is a second opinion. Do not connect extra beacon devices.
- [ ] Connect the temporary setup camera and confirm `cam-status` reports `on`.
- [ ] Clear people and movable objects from the sensing area before the baseline.
- [ ] Let the narrator warm its local model in the background. The template path remains available, so do not delay the demo.
- [ ] Confirm the proof strip renders JSON `null` as `__`.

Do not start while the screen says `NO DATA` or `SENSOR BLIND`. Neither state means the room is empty.

## Baseline and training

1. Set label mode to `off`, clear the sensing strip and desk, and start the baseline.
2. Wait for `baseline_done`; confirm every required link is healthy and health returns to `ok`.
3. Start a named training recording and set label mode to `person`.
4. Step into and out of the spot, move, and stand still while the camera teacher supplies presence and motion labels.
5. Stop recording, start training, and wait for the `trained` event.
6. Confirm `model.trained` is true and a radio prediction appears.

If a step fails, fix it and repeat the baseline or lesson. Do not carry failed calibration into the demo.

## Three-minute desk round

Use these exact beat names and keep them in this order.

1. **Found you:** Start with the camera disconnected. Ask the judge to step up to the desk, into the sensing strip. Show a fresh `person` prediction and say, “Found you. Camera disconnected.” Do not substitute a numeric camera claim while proof remains pending.
2. **Teach the room:** Connect the camera, start the fresh judge lesson, and display `Lesson time: __ s`. Show labels, not an image. Wait for successful training before continuing.
3. **Camera unplug:** Unplug the camera in one continuous shot. Follow the camera-unplug proof below and leave the cable visible.
4. **Still follows:** Ask the judge to move and then stand still in the spot. Show presence and motion continuing from radio alone, with Wi-Fi across the gap as the main sensor. If a required link goes blind, say so and stop; never call it empty.
5. **Arm the space:** Ask the judge to step out. Use the arm control only if the current build exposes contract v2 `armed` state, emits `armed`, and the phone page is connected to the live feed.
6. **Intrusion alert:** Ask the judge to re-enter and stay in the spot. Continue only after the board emits the live `intrusion` event and the phone page shows it. A passer-by gets no intrusion alert. Do not identify the judge or claim crowd counting.
7. **Ask the room:** Ask the prepared question only if the current build can answer from its local timestamped event records. Read the returned facts; do not improvise an answer.
8. **Proof:** Finish on `/proof.json`. Show `Images stored: __` and `Bytes sent outside local network: __` until proof replaces them, but say only completed values. Close with “We dug into a signal every building already has, for rooms where cameras cannot go. Taught by a camera. Runs without one. Next is the same lesson on real access points. We would like to keep building it.”

If the feature gate for **Arm the space**, **Intrusion alert**, or **Ask the room** fails, stop the live sequence after **Still follows**, use the matching **At the desk** sentence, then go directly to **Proof**.

## Camera-unplug proof

1. Keep the live laptop screen and camera cable visible together.
2. Unplug the camera without cutting away.
3. Confirm `cam-status` changes to `off` and `teacher` becomes null.
4. Confirm radio state continues to update and the source remains `live`.
5. Leave the camera unplugged for the rest of live sensing.

The camera supplies temporary setup labels. The demo must not show or save an image.

## Five-minute finalist round

Run the same one-spot kit: **Found you**, **Teach the room**, **Camera unplug**, **Still follows**, **Arm the space**, **Intrusion alert**, **Ask the room**, and **Proof** in that same order.

After the primary path, use only the extensions that passed preflight:

- **No-movement alert and check-in:** Wait for the configured local alert, ask the judge to lean aside for the “I'm okay” check, and confirm `checkin-toast` clears it. Do not claim success before that confirmation.
- **Tray and router advice:** Ask Alexander to place the tray across the gap. Confirm the deployed advisor uses the cross-gap Wi-Fi link `pi5>pi5b:wifi` and its configured drop threshold; stop this beat if it still targets the short desk link. Wait for `advice-text`, move only to a spot from `/nodes.json`, send `router_moved`, and report the before/after result only if proof contains it.
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

If a device was knocked, secure it and restore the positions from `radio/nodes.json`. Keep everyone out of the spot, then start `baseline {keep_model: true}` and wait for its `20 s` capture to finish. It can run with the camera unplugged and keeps the trained model; do not use plain `baseline {}` for this same-layout recovery.

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

Do not answer from memory. Use the **Ask the room is slow or wrong** sentence, show the local event records with Replay, and continue to **Proof**.

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
