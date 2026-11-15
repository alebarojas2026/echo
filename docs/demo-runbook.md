# Echo Demo Runbook

A witness that never watches. Echo knows when someone is in a space, keeps a record nobody can edit, and tells you what happened. No camera, no microphone. This checklist follows `CONTRACTS.md` v2. The desk round is the primary path; the finalist round comes second. The only numbers said are the sentences in [numbers-to-say.md](numbers-to-say.md); anything else missing from `PROOF.md` stays `__`.

## At the desk

| Role | Name | Does | Never |
|---|---|---|---|
| Talker | __ | Says the round, points at the right screen | Touches a laptop |
| Operator | __ | Drives the main laptop: arm, disarm, "What happened?", Prove it, reset between judges | Explains while typing |
| Hardware | __ | Handles the Arduino and the two Pis, unplugs and replugs Pi B, fixes anything knocked | Leaves the desk |
| Spotter | __ | Keeps the gap clear of passers-by and places a second judge | Stands in the gap |

Keep at least two people at the desk for every half hour:

| Time | Person | Person |
|---|---|---|
| 1:00–1:30 PM | __ | __ |
| 1:30–2:00 PM | __ | __ |
| 2:00–2:30 PM | __ | __ |
| 2:30–3:00 PM | __ | __ |

Round one is the science-fair round at the desk, from about 1:00 to 3:00 PM. The judges pick six projects for round two; keep the five-minute round ready.

The Hardware role answers radio and hardware questions. The Operator answers record, signature and proof-number questions. The Talker answers cost and what's next.

While the Operator fixes a failure, the Talker says exactly one of these:

- **Sensor blind:** “That's the honest failure. The Wi-Fi line stopped reporting, so it says blind instead of guessing the spot is empty. Give us a moment.”
- **No data:** “The screen lost the board's feed, so it says no data, not empty. Reconnecting.”
- **Nobody found:** “It needs a few seconds on the line. Stand right between the two devices and hold still.”
- **"What happened?" is slow or wrong:** “The language model on this board is tiny. The records it reads from are right; here they are.” Open the records the answer cites.

### Judge-day screens

The stand uses several screens, and every one of them joins the kit's own Wi-Fi directly. No web link, no relay through a phone or another laptop.

| Screen | Shows | Address |
|---|---|---|
| Main laptop, facing the judge | The 3D hall, the figure, the headline | `http://192.168.77.2:8080/` |
| Second laptop | The engine room: the record, the signatures, Prove it | `http://192.168.77.2:8080/engine/` |
| A third laptop or a phone | The alarm page | `http://192.168.77.2:8080/phone/` |
| A fourth laptop (not on the kit's Wi-Fi) | A looping slide: the one line and the measured sentences | none |

Rules for every screen: one page per device, full screen, in the front tab (a hidden tab draws no frames); plugged in; sleep and dimming off; joined to the kit's Wi-Fi the night before and checked once. A laptop on the kit's Wi-Fi has no internet, which is expected.

At the stand, place the screen once: on the main laptop press `P`, click the desk the board is on, press `G` if Pi B is on the other side, press `Enter`. The page loads again and says "Saved: Row N, block M" with your row and block. Then take the empty baseline.

In the script: the judge looks at the main laptop; the alarm page turns red when armed and somebody steps in; the engine room is where "What happened?" shows its steps and where Prove it is pressed.

## Preflight

### Before the first judge

Record the operator, checker, and actual finish time beside each step. These are scheduling blanks, not performance results.

| Order | Action | Time | Operator / checker |
|---|---|---|---|
| 1 | Power up the Arduino UNO Q, Pi A, Pi B, and the laptops. No webcam is plugged in | __ | __ |
| 2 | Set the board's clock from the laptop using the operator clock control; disarm first, then wait for reconnection. Pi B's clock resets whenever it loses power: ask Alexander to set it after any power-up, before the baseline | __ | __ |
| 3 | Write down the commit the deploy printed and the served screen build: board __, screen __, previous good tag __ | __ | __ |
| 4 | Confirm the layout is the gate on all three devices: `python3 -m radio.use_layout gate` reports three devices | __ | __ |
| 5 | Capture the empty baseline: nobody within 2 m of the gap, press Baseline in the operator drawer (O key), wait for "baseline done". The headline then says "Nobody is here", and the empty line reads about -44 dBm or better | __ | __ |
| 6 | Run `python scripts/demo_check.py`; fix every FAIL using its printed instruction | __ | __ |
| 7 | Open `http://192.168.77.2:8080/chain` twice, a little apart: `head.seq` is higher, `"verified": true`, and each Pi is a witness with `"sig_ok": true` and `"silent": false` | __ | __ |
| 8 | Have someone outside the team walk the full round | __ | __ |
| 9 | Ask "What happened?" using the real local model and open the records it cites | __ | __ |

The baseline comes first, before anything is judged, and again after every deploy, after Pi B is unplugged and replugged, and after any device is moved. A FAIL from the check is a stop: page/layout means check the web server and deployed layout; WebSocket means check bus and brain; clock means set time while idle; links/health means inspect the named radio; records means check `radio-sight-store`; Ask means inspect the answer service and local model.

The Pi keys are made and enrolled once, at deploy: each Pi's private key stays on that Pi and is never copied or pasted anywhere. After any restart, check the signing program is running on each Pi (`journalctl -u radio-sight-witness -n 2 -o cat`). If `/chain` lists no witnesses, the board has not read its key file; ask Alexander.

Secure Pi B's power cable: it has come out once. A small nudge of one device costs the margin, so the devices are placed and the empty line checked before each session.

**From Sunday 9:30 AM the board runs a tagged commit. Nothing goes onto it afterwards except a rollback to the previous tag: no deploy or screen build pushed during judging.**

**Before any restart, save the logs: `journalctl -u 'radio-sight-*' --since -5min > incident-<time>.txt`. Replace `<time>` with the actual incident time in the local filename.**

### Going back

Record last good board tag __, last good screen build __, operator __, checker __, and measured recovery time __ s. Save the logs first.

Going back is one command on each device, with the recorded previous tag:

1. On the board and on Pi A: `git checkout radio/nodes.json && board/deploy.sh <last-good-tag> --no-check && python3 -m radio.use_layout gate && sudo systemctl restart 'radio-sight-*'`
2. On Pi B, the same with `ROLE=pib` before `board/deploy.sh`.
3. On the laptop: `board/push-web.sh --back` restores the previous screen build.
4. Take the empty baseline, then `python scripts/demo_check.py`; look at the screen and every check before admitting another judge.

Never rebuild or copy a screen bundle over the hotspot while sensing runs.

### The live path

- [ ] Connect the UNO Q and Pi A with the direct Ethernet cable.
- [ ] Ask Alexander to run `sudo bash pi/eth.sh` on the Pi and `sudo bash board/eth.sh` on the UNO Q.
- [ ] Ask Alexander to run `sudo bash pi/ap.sh` on the Pi and `sudo bash radio/wifi_join.sh` on the UNO Q.
- [ ] Join the demo laptop to the Pi's private hotspot. Do not copy files or bundles over it during a demo or recording.
- [ ] Open `http://192.168.77.2:8080/` in the laptop browser.
- [ ] Confirm `/nodes.json` and `/proof.json` load from that address.
- [ ] Confirm `ws://192.168.77.2:8765/ws` produces contract v2 `state` messages.
- [ ] Confirm the source is `live`, the feed is fresh, and `health.status` is `ok`.
- [ ] Power Pi B, join it to Pi A's hotspot, and confirm its reader sends through Pi A to the board.
- [ ] Set the three devices for one spot: Arduino UNO Q and Pi A together on the desk, Pi B about a metre away at desk height. On a chair seat it fails. Confirm the deployed `radio/nodes.json` matches this kit.
- [ ] Keep the gap between Pi A and Pi B clear. Wi-Fi from Pi A to Pi B is the only line that decides; no other radio line votes.
- [ ] Let the narrator warm its local model in the background. The template path remains available, so do not delay the demo.

Do not start while the screen says `NO DATA` or `SENSOR BLIND`. Neither state means the spot is empty.

## Three-minute desk round

Follow the exact spoken script in [pitch.md](pitch.md). These are rehearsal allocations, not measured task durations; never say an alert or an answer arrived before it did.

| Time | Beat | Speaker and actions | Screen and gate |
|---|---|---|---|
| 0:00–0:30 | **Found you** | Talker invites the judge onto the spot; judge stands still until the no-movement alert, then steps aside and back | Main laptop: the figure and the headline; the no-movement alert; "Check-in received" |
| 0:30–1:00 | **Intrusion alert** | Judge steps out; Operator arms only while empty; judge steps in and stays | Armed state; the alarm page turns red with the live intrusion |
| 1:00–1:25 | **Tamper alert** | Still armed, Hardware unplugs Pi B, waits for the alert, plugs it back in | The tamper alert names Pi B; the engine room shows that witness silent and the record still counting |
| 1:25–2:00 | **What happened** | Operator disarms and taps "What happened?" | The story in plain words with clock times, its steps and the records it used |
| 2:00–2:30 | **Engine room** | Talker points to the second laptop; Operator presses Prove it | The record counting, the signatures, and the check naming the altered record |
| 2:30–3:00 | **Proof** | Talker reads the measured sentences from the slide and closes | The looping slide, word for word from numbers-to-say.md |

While Pi B is unplugged the screen says the sensor is blind. That is right: its Wi-Fi line is the sensor. The rest of the round needs no sensing. After the judge leaves, wait for Pi B to rejoin and its witness to sign again, set Pi B's clock, then take the empty baseline before the next judge.

For the “I'm okay” check the judge steps fully out of the line and back within a few seconds, then waits for "Check-in received". Do not claim it before that confirmation.

**If interrupted:** cut the Tamper alert first, then the Engine room, then shorten Proof to its closing line. Keep Found you, and at least one of Intrusion alert or What happened. If a beat did not pass preflight, say what it would have shown and move on; do not stage it.

Feature gates before admitting a judge:
- **Found you:** a person standing in the gap for a few seconds is found; nobody is found with the gap empty; standing still raises the no-movement alert and stepping aside and back clears it.
- **Intrusion alert:** stay until the live event arrives.
- **Tamper alert:** rehearse unplugging and replugging Pi B; the alert names it, the witness comes back by itself, and the baseline is taken again.
- **What happened:** the answer cites the board's records; show those records if the wording fails.
- **Engine room:** Prove it reports the altered record, and `/chain/verify` still says the real record is whole.
- **Proof:** only the sentences in numbers-to-say.md are spoken; no bare percentage and nothing simulated.

## Five-minute finalist round

Run the same six beats and one-spot kit. Add only what passed preflight: a second question, the incident report and more of the measured sentences. If generation is unavailable, use factual template wording; never invent an event.

## If asked

- The UNO Q makes the decision, keeps and seals the record, checks the signatures and answers questions on its Dragonwing CPU. The Pis provide the Wi-Fi line and sign the record; they run no model.
- These development boards stand in for an access point and a device a building already has.
- Echo senses one spot. It does not know who a person is or which part of a room they are in.
- The no-movement alert notices sustained stillness, not its cause.
- A person needs a few seconds on the line. A quick pass through the gap is not something we claim.

## Finish the live demo

Alexander handles the Pis; the Operator handles software controls.

1. If Pi B was unplugged, confirm it is plugged in and back on the hotspot.
2. Pi B's clock resets whenever it loses power, and unplugging it is a power loss: ask Alexander to set Pi B's clock before the baseline.
3. Everyone steps away from the gap and stays out.
4. Disarm if needed and send `reset`.
5. Take the empty baseline and wait for "baseline done"; confirm health is `ok` and the headline says "Nobody is here".
6. Confirm both witnesses are signing again on the engine room.
7. The narrator warms its normal sentence prompt again in the background after the recap; do not hold the next judge for that warmup.

If a device was knocked, put it back, keep everyone out of the gap, and take the empty baseline again before the next judge.

## Proof check

The measured sentences live in [numbers-to-say.md](numbers-to-say.md), each quoting a row of `PROOF.md`. Before judging, check the slide against that file word for word. On the screen, open `/proof.json` and match each displayed value to the file.

A JSON `null` must render as `__`. Never replace it with an estimate. Say the count and its range, never a bare percentage. Say "replayed from recordings taken on the kit" for every sentence except the one live run.

## Recovery

### `NO DATA`

The last state is stale. Confirm the page loads, then check the WebSocket and the brain. Do not describe the spot as empty until fresh state resumes.

### `SENSOR BLIND`

The Wi-Fi line from Pi A to Pi B is not reporting. Check that Pi B has power and is on the hotspot. Decisions stay null, and alert and intrusion decisions pause until the line recovers. If Pi B lost power, set its clock, then take the baseline again.

### Nobody is found

Check that Pi B is at desk height and the gap is about a metre. Clear the gap and take the empty baseline again. A person must stand in the line between the two devices for a few seconds.

### Armed or alarm-page failure

Disarm, keep the judge outside the gap, and check the alarm page is on the kit's Wi-Fi and in the front tab. If the armed state, the `intrusion` event, or its card is missing, skip that beat; do not simulate it.

### "What happened?" fails

Do not answer from memory. Use the **"What happened?" is slow or wrong** sentence, show the records, and continue to the **Engine room**.

### A witness stays silent

On that Pi, `journalctl -u radio-sight-witness -n 2 -o cat` shows whether it is signing. The record keeps counting without it and notes the gap; say so, and ask Alexander before restarting anything.

### Narration is unavailable

Continue with the on-board template explanation. The narrator keeps warming locally after startup, a failed call, and the recap; never delay the demo or invent a description.

## After the demo

- [ ] Disarm and reset.
- [ ] Save proof output with its method, sample size, date, and commit.
- [ ] Restore every device to its `/nodes.json` position.
- [ ] Confirm no image or video file was created.
- [ ] Keep every unmeasured public result as `__`.
