# Radio Sight Demo Runbook

Use this checklist for the live demo. It follows `CONTRACTS.md` v2. Do not fill a proof value by hand: an unmeasured result stays `__`.

## Preflight

- [ ] Connect the board and Pi with the direct Ethernet cable.
- [ ] Confirm the Pi's 5 GHz sensing hotspot is running and the board joined it.
- [ ] Open `http://192.168.77.2:8080` on the demo screen.
- [ ] Confirm `/nodes.json` and `/proof.json` load from the same address.
- [ ] Confirm the live WebSocket at `ws://192.168.77.2:8765/ws` is producing contract v2 `state` messages.
- [ ] Confirm the source badge says `live`, the feed is fresh, and `health.status` is `ok`.
- [ ] Put the router at `S-home`. Predictions are intentionally unavailable anywhere else.
- [ ] Connect the setup camera and confirm `cam-status` reports `on`.
- [ ] Keep the square clear of people and movable objects before the baseline.

Do not start the demo while the screen says `NO DATA` or `SENSOR BLIND`. Neither state means that the room is empty.

## Baseline and training

1. Set label mode to `off` and keep the square empty.
2. Start the baseline. Keep every link healthy and the square clear for the full capture.
3. Wait for the `baseline_done` event and confirm health returns to `ok`.
4. Start a training recording with a session name, purpose, and walker.
5. Set label mode to `person`. Walk the marked zones while the camera teacher supplies location and motion labels.
6. Stop the recording, start training, and wait for the `trained` event.
7. Confirm `model.trained` is true and a radio prediction appears while the router is at home.

If the baseline or training fails, fix the failed preflight item and repeat the step. Do not carry a failed calibration into the demo.

## Live demo sequence

1. **Judge walks in:** Ask the judge to enter the marked square. Show `pred-kind` as `person`, `pred-motion` as `moving`, and the predicted zone.
2. **Radio X-ray:** Point out the fresh human layer and the highlighted radio links. Describe the static layer as change since the baseline, never as a wall map.
3. **No-movement alert:** Ask the judge to remain still in a zone with a configured limit. Wait for the alert banner; do not call it anything else.
4. **Wave check-in:** Ask for the practiced back-and-forth motion without changing zones. Wait for the `checkin-toast` and confirm the alert clears.
5. **Tray vs person:** Place the metal tray at its marked spot. Show the object marker only after the radio state reports an object rather than a person.
6. **Router advice:** Wait for the generated `advice-text`, show the recommended spot and before value, move the router there, and send `router_moved` with that spot. A null prediction during the move is expected. Wait for the after value and advice result; report improvement only from measured proof data, otherwise show `__`.
7. **Camera unplug:** Follow the camera-unplug proof below and keep the disconnected cable visible.
8. **Proof:** Finish on the proof strip. Every missing measurement must remain `__`.

## Camera-unplug proof

1. Keep the live screen and camera cable visible together.
2. Unplug the camera in one continuous shot.
3. Confirm `cam-status` changes to `off` and `teacher` becomes null.
4. Confirm the radio state continues to update and the source remains `live`.
5. Leave the camera unplugged for the rest of the live sensing demo.

The camera supplies temporary setup labels only. The demo must not show or save an image.

## Finish the live demo

Alexander handles the tray and Pi. Keep software commands with the operator.

1. Ask Alexander to remove the tray.
2. Wait until the object marker and static change clear.
3. Ask Alexander to return the Pi to `S-home`.
4. Only then send `router_home`.
5. Wait until prediction resumes or the automatic baseline finishes, then confirm health is `ok`.
6. Stop any active recording and send `reset` before the next judge.

Call the alert a `no-movement alert`. Reset it with a check-in or the reset control.

## Proof check

Open `/proof.json` and match each displayed proof value to the file:

- zone accuracy and confidence interval;
- person-vs-object result;
- false alarms per minute;
- training and decision timing;
- power measurements;
- bytes out, images stored, and models on board; and
- measurement date and commit.

A JSON `null` must render as `__`. Never replace it with an estimate. State the method and limits with every measured result.

## Recovery

### `NO DATA`

The last state is stale. Confirm the web page still loads, then check the WebSocket and sensing-model process. Do not describe the room as empty until fresh state resumes.

### `SENSOR BLIND`

At least one classifier link is unhealthy. Check the named blind link, its reader, and its radio node. Predictions remain null and alert timers pause until the links are healthy again.

### Camera failure

Before training, reconnect the camera and confirm `cam-status` returns to `on`. After successful training, `off` is the expected camera-unplug state; continue only if the radio feed remains healthy.

### Router move does not recover

Return the router to `S-home` and send `router_home`. If the home links do not return to their baseline range, let the automatic baseline finish before continuing.

### Narration is unavailable

Continue with the on-board template explanation. Do not delay or invent an event description while waiting for the language model.

## After the demo

- [ ] Stop any active recording.
- [ ] Save proof output with its measurement date and commit.
- [ ] Leave the router at `S-home`.
- [ ] Confirm no image or video file was created.
- [ ] Keep every unmeasured public result as `__`.
