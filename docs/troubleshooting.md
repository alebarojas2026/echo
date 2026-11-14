# Radio Sight Live-Demo Troubleshooting

Use this guide when the live demo is not ready. Fix the first failed check, then start again at the top. Do not interpret a missing prediction as an empty room.

## Fast checks

1. **Page:** Open `http://192.168.77.2:8080/?src=ws`. Confirm `/nodes.json` and `/proof.json` load from the same board address.
2. **Source:** Confirm the source badge says `live`. A mock or replay source is not live proof.
3. **Feed:** Confirm the screen does not say `NO DATA` and that contract v2 state is arriving from `ws://192.168.77.2:8765/ws`.
4. **Radio health:** Confirm health is `ok`, every required link is updating, and the screen does not say `SENSOR BLIND`.
5. **Router:** Confirm the Pi is at `S-home`. Predictions are intentionally null while the router is elsewhere.
6. **Model:** Confirm `model.trained` is true. If it is false, finish a valid baseline and training run before continuing.

`NO DATA` means the state feed is stale. `SENSOR BLIND` means at least one classifier link is unhealthy. Neither state means that the room is empty.

## The page does not load

1. On the Pi, open `http://192.168.77.2:8080/proof.json`. If it loads, reopen the kiosk at the URL ending in `?src=ws`.
2. If it does not load, confirm the direct Ethernet path between the Pi and the UNO Q hub is connected. Application traffic uses that cable, not the sensing hotspot.
3. On the board, confirm `radio-sight-serve.service` is active.
4. Do not move the Pi onto venue Wi-Fi. Radio Sight uses its own local network.

If a cable, powered hub, board, Pi, or display must be handled, stop and send a note in this form: `needs Alexander: check the direct Ethernet cable and confirm /proof.json loads on the Pi`. Alexander owns every physical hardware action.

## The screen says `NO DATA`

The web page loaded, but the latest state is stale.

1. Confirm the kiosk URL ends in `?src=ws`; without it, the page is not connected to the live feed.
2. Confirm `radio-sight-brain.service` and `radio-sight-bus.service` are active on the board.
3. Confirm the live WebSocket is bound to the board's Ethernet address and the page reconnects to it.
4. Once fresh state resumes, verify the source badge says `live` before continuing.

Do not call this state empty. The screen needs a current state message before it can make any room claim.

## The screen says `SENSOR BLIND`

At least one classifier link is stale or has an unexplained signal jump. Predictions stay null and alert timers pause until health recovers.

A steady below-baseline drop is treated as an object, not a broken link. If a tray or other object appears and the screen becomes blind, inspect `health.blind` for the actual failed link instead of treating the object's steady change as a fault.

1. Read the named entries in `health.blind` and match them to the link list.
2. For `pi5>unoq:wifi`, confirm the Pi hotspot is running, the board is joined to it, and Wi-Fi power saving is off.
3. For a Bluetooth link received by the UNO Q, confirm `radio-sight-hci-scan.service` is active.
4. For a Bluetooth link received by the Pi, confirm the Pi radio-node service is active.
5. Confirm the east and west beacons advertise the expected manufacturer data. Match advertised data, never a device address.
6. Wait for health to return to `ok`; do not replace a null prediction with a guess.

Any beacon, antenna, phone, cable, or node placement change needs Alexander. State the exact blind link in the `needs Alexander:` note.

## The camera is off or stalled

The camera supplies setup labels only. It saves no image or video.

- Before baseline or training, reconnect or restart the camera path and wait for `cam-status` to report `on`.
- During baseline, keep label mode `off` and keep the square clear.
- After successful training, camera `off` is expected for the radio-only demo. Continue if the radio feed is live and healthy.
- If the camera moved, redo the camera calibration before collecting labels again.

The public proof is that sensing continues after the camera is unplugged. Radio Sight works behind a curtain because it measures radio change; the camera is not part of live inference.

## Baseline or training will not complete

1. Put the router at `S-home` and confirm every required link is healthy.
2. For baseline, confirm label mode is `off` and keep the square clear of people and movable objects.
3. If a person enters or health stops being `ok`, clear the square, fix the failed link, and restart the baseline.
4. For training, confirm the camera is `on`, the person is inside the calibrated square, and the label mode matches the session purpose.
5. Drop any window with no label or a clipped label. Do not treat it as training evidence.
6. Wait for `baseline_done` before training and for `trained` before judging predictions.

After moving into the presentation room, place the final tape, redo the camera calibration, baseline, and training there. Build-room calibration is not presentation evidence.

## Predictions disappear after moving the router

This is expected while the router is away from home.

1. Complete the advised measurement and record only the before and after values the system produces.
2. Return the router to `S-home` before sending `router_home`.
3. If the home links do not settle back to baseline, let the automatic baseline finish.
4. Continue only after predictions resume and radio health is `ok`.

Do not send `router_home` while the tray or Pi is still away from the home marker.

## A no-movement alert will not clear

- The still timer uses smoothed decisions. Brief motion noise does not reset it: the model must produce five moving decisions in a row. A different zone or kind resets the timer only after it holds the majority of the last ten decisions.
- A check-in or `reset_alert` clears the alert.
- A zone change does not clear an active alert by itself.
- `reset` is the between-judges command; it clears the alert, still timer, check-in, advice, and narration.
- If radio health is blind or the router is away from home, predictions are null and the alert timer pauses. Restore a healthy prediction before testing the alert again.

Use the phrase **no-movement alert** in the demo. Objects never start this alert.

## Proof values show `__`

`__` means the corresponding value in `/proof.json` is still null or unavailable. It is not a failure in the display.

1. Check the proof run for a `missing:` line and collect the named evidence.
2. Keep held-out sessions separate from training sessions.
3. Keep the value as `__` until the proof pipeline produces a measured result.
4. Never type an estimate into the page or a public document.

The Pi runs no model. Training, inference, radio health, alert logic, and proof timing run locally on the UNO Q, on the Dragonwing CPU.

## Return to a known state

Before the next judge:

- return the router to `S-home`;
- stop any active recording;
- send `reset`;
- confirm the page uses the live WebSocket;
- confirm camera state matches the next demo step;
- confirm health is `ok` and the model is trained; and
- leave every missing proof result as `__`.
