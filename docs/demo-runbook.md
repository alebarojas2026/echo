# Echo Demo Runbook

Safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras. This checklist follows `CONTRACTS.md` v2. The desk round is the primary path; the finalist extension comes second. A result missing from `PROOF.md` stays `__`.

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
| 9 | Copy what the board learned to the laptop over Ethernet, using the verified backup procedure from #679 | __ | __ |

Run `python scripts/demo_check.py` again after the lesson. A FAIL is a stop: page/layout means check the web server and deployed layout; WebSocket means check bus and brain; clock means set time while idle; links/health means inspect the named radio; model means baseline and lesson; records means check `radio-sight-store`; Ask means inspect the answer service and local model. A degraded-health WARN still has predictions; inspect the named device without calling it empty.

**From Sunday 9:30 AM the board runs a tagged commit. Nothing goes onto it afterwards except a rollback to the previous tag: no deploy or screen build pushed during judging.**

**Before any restart, save the logs: `journalctl -u 'radio-sight-*' --since -5min > incident-<time>.txt`. Replace `<time>` with the actual incident time in the local filename.**

### Going back

Record last good board tag __, last good screen build __, operator __, checker __, and measured recovery time __ s. Save the logs first. The recovery sequence from #678 is:

1. `board/deploy.sh <last-good-tag>` — use the recorded previous tag, already available locally.
2. `board/push-web.sh --back` — restore the previous screen build locally on the board.
3. `python scripts/demo_check.py` — inspect the screen and every check before admitting another judge.

The screen `--back` option and `board/keep.sh save` backup are tracked in #678 and #679. Confirm they exist in the deployed version and have passed a real restore before using this checklist as a recovery guarantee. Never rebuild or copy a screen bundle over the hotspot while the model runs.

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

Follow the exact spoken script in [pitch.md](pitch.md). These are rehearsal allocations, not measured task durations; never claim a lesson or alert finished before it did.

| Time | Beat | Speaker and actions | Screen and gate |
|---|---|---|---|
| 0:00–0:25 | **Found you** | Talker invites judge into the spot; camera disconnected | Fresh presence and Live signal; Wi-Fi across the gap is primary |
| 0:25–1:05 | **Teach the room** | Talker explains; Operator connects teacher and runs lesson | Camera teaching, labels, progress and trained confirmation; no image |
| 1:05–1:35 | **Camera unplug** | Hardware unplugs; judge moves then stands still | Teacher off, radio only, Still follows and live privacy panel |
| 1:35–2:00 | **Intrusion alert** | Operator arms only while empty; judge returns and stays | Armed state, sustained intrusion event and matching phone card |
| 2:00–2:30 | **Dead zone** | Disarm; nobody in spot; Hardware adds object, then clears it or moves Pi B | Object decision, cross-gap Wi-Fi drop, advice and verified gain |
| 2:30–3:00 | **Ask the room and Proof** | Operator asks prepared question, shows source rows and proof; Talker closes | Local answer, factual records and completed proof tiles |

Pi A stays beside the cabled hub. The dead-zone beat requires nobody present and an object decision on `pi5>pi5b:wifi`; a person is never a dead zone. Confirm the deployed advisor uses that link and the configured drop threshold. Stop this beat if it still targets the short desk link or asks for a large router move. Gain comes from clearing the object or moving Pi B, with before/after evidence; do not improvise hardware or commands during judging.

**If interrupted:** cut optional Replay, Incident report and Tamper alert first, then the extra Ask question, then teaching explanation. Keep Found you, Camera unplug, and at least one of Intrusion alert or Dead zone. With an already trained model, omit a fresh lesson honestly; do not pretend it happened. If neither outcome passed preflight, state the limit and finish on proof.

Feature gates before admitting a judge:
- **Live signal:** stepping into the spot changes the cross-gap trace; no side prediction is promised.
- **Privacy:** teacher off and null labels after unplug; counts come from the live privacy meter and proof, never invented zeros.
- **Intrusion:** stay until the live event arrives; a walk-through may show passed by without an alert, but its error rate is unclaimed.
- **Tamper alert:** rehearse Pi B disconnection and reconnection; verify the named event, `tamper_cleared` and healthy sensing before continuing.
- **Ask the room:** the answer must cite the board's records; show the actual rows if wording fails.
- **Replay:** a recorded banner stays visible; missing records stay unknown.
- **Incident report:** an actual saved armed stretch supplies all facts.
- **Proof:** only completed results may be spoken; missing values remain `__` in records and are omitted from judge tiles.

## Camera-unplug proof

1. Keep the live laptop screen and camera cable visible together.
2. Unplug the camera without cutting away.
3. Confirm `cam-status` changes to `off` and `teacher` becomes null.
4. Confirm radio state continues to update and the source remains `live`.
5. Leave the camera unplugged for the rest of live sensing.

The camera supplies temporary setup labels. The demo must not show or save an image.

## Five-minute finalist round

Run the same six beats and one-spot kit. Add only extensions that passed preflight: Tamper alert, Replay, Incident report and the no-movement alert.

For the “I'm okay” check, ask the judge to lean aside and confirm `checkin-toast` clears the no-movement alert. Do not claim success before that confirmation. If generation is unavailable, use factual template wording; never invent an event.

## If asked

- The UNO Q performs local training and inference on its Dragonwing CPU. The Pi provides network and radio and runs no model.
- These development boards stand in for the radios or access points a building already has.
- The no-movement alert notices sustained stillness, not its cause.
- The dead-zone view reports which measured link something starts blocking. A full building coverage map is future work.

## Finish the live demo

Alexander handles the tray and Pi; the operator handles software controls.

1. If the tray was used, ask Alexander to remove it and wait for the object marker and static change to clear.
2. If Pi B moved, ask Alexander to return Pi B to its recorded position; use only the reset procedure rehearsed on this deployed build.
3. Everyone steps away from the sensing area and its edge, including Alexander once Pi B is home, and stays out until a prediction returns or `baseline_done` appears.
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

### Object clearing or Pi B move does not recover

Clear the object, return Pi B to its recorded position from `/nodes.json`, and repeat the rehearsed baseline procedure. Keep Pi A beside the cabled hub; do not claim gain until healthy sensing and the before/after check return.

### Narration is unavailable

Continue with the on-board template explanation. The narrator keeps warming locally after startup, a failed call, and the recap; never delay the demo or invent a description.

## After the demo

- [ ] Disarm and reset.
- [ ] Stop active recording.
- [ ] Save proof output with its method, sample size, date, and commit.
- [ ] Restore every node to its `/nodes.json` position.
- [ ] Confirm no image or video file was created.
- [ ] Keep every unmeasured public result as `__`.
