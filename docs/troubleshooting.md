# Echo Live-Demo Troubleshooting

Use this guide when the live demo is not ready. Fix the first failed check, then start again at the top. Do not read a missing decision as an empty spot.

## Fast checks

| Failure point | What the screen may say | First check |
|---|---|---|
| Pi B | SENSOR BLIND, or a witness shown silent | Power cable and hotspot join; its Wi-Fi line is the sensor |
| Pi A or Ethernet cable | NO DATA or page unavailable | Pi A power and the direct cable to the board's hub |
| Brain | NO DATA | `radio-sight-brain` and `radio-sight-bus`; save logs before a restart |
| Store | Empty history, or the record not counting | `radio-sight-store`; unknown records are not an empty spot |
| Signing | A witness silent, or none listed | `radio-sight-witness` on that Pi; the board's local key file |
| Question model | A slow answer | Local `radio-sight-llm`; open the records the answer cites |
| Laptop Wi-Fi | Disconnected page or NO DATA | Join Pi A's hotspot again, then open the page again |

1. **Page:** Open `http://192.168.77.2:8080/`. Confirm `/nodes.json` and `/proof.json` load from the same board address.
2. **Source:** Confirm the source says `live`. A mock or replay source is not live proof.
3. **Feed:** Confirm the screen does not say `NO DATA` and that contract v2 state is arriving from `ws://192.168.77.2:8765/ws`.
4. **Line:** Confirm health is `ok`, `pi5>pi5b:wifi` is updating, and the screen does not say `SENSOR BLIND`.
5. **Baseline:** Confirm a baseline was taken with the spot empty since the last deploy, power-up or move.
6. **Record:** Open `http://192.168.77.2:8080/chain` and confirm the record is counting, verified, and signed by both Pis.

`NO DATA` means the state feed is stale. `SENSOR BLIND` means the Wi-Fi line is not reporting. Neither state means that the spot is empty.

## The page does not load

1. Confirm the laptop is joined to the Pi hotspot, then open `http://192.168.77.2:8080/proof.json`. If it loads, reload the page.
2. If it does not load, confirm the direct Ethernet path between Pi A and the UNO Q hub is connected. Ask Alexander to rerun `sudo bash pi/eth.sh` on Pi A and `sudo bash board/eth.sh` on the UNO Q if either cable address is missing.
3. On the board, confirm `radio-sight-serve.service` is active.
4. Do not move the Pi onto venue Wi-Fi. Echo uses its own local network.

If a cable, powered hub, board, Pi, or laptop must be handled, stop and send a note in this form: `needs Alexander: check the direct Ethernet cable and confirm /proof.json loads in the laptop browser`. Alexander owns every physical hardware action.

## The screen says `NO DATA`

The web page loaded, but the latest state is stale.

1. Confirm the page is in the front tab; a hidden tab draws no frames.
2. Confirm `radio-sight-brain.service` and `radio-sight-bus.service` are active on the board.
3. Confirm the live WebSocket is bound to the board's Ethernet address and Pi A routes WebSocket port `8765` as well as HTTP port `8080` to the direct cable.
4. Once fresh state resumes, verify the source says `live` before continuing.

Do not call this state empty. The screen needs a current state message before it can say anything about the spot.

## The screen says `SENSOR BLIND`

The Wi-Fi line from Pi A to Pi B is stale. Decisions stay null and alert timers pause until it recovers. This is the expected state while Pi B is unplugged on purpose.

1. Ask Alexander to confirm Pi B is powered and its power cable is secure.
2. On Pi B, run `python3 -m pi.check --node pi5b` and confirm the board bus at `192.168.77.2:5600` is reachable and `pi5>pi5b:wifi` is listed and updating.
3. Confirm Pi A's hotspot is running and its hotspot-to-Ethernet forwarding is active.
4. If Pi B lost power, its clock has reset: set Pi B's clock before anything else.
5. Wait for health to return to `ok`, then take the baseline with the spot empty. Do not replace a null decision with a guess.

Pi B has no cable and its address comes from DHCP: do not record it. Any device, cable or placement change needs Alexander. State what the screen says in the `needs Alexander:` note.

## Nobody is found, or somebody is found in an empty spot

1. Check the placement: Pi B across a gap of 85 to 100 cm, at desk height. On a chair seat it fails.
2. Check nothing was nudged. A small move of one device costs the margin; the empty line should read about -44 dBm or better.
3. Clear the gap, keep everyone 2 m away, and take the `20 s` baseline again. Wait for `baseline_done`.
4. A person must stand in the line between the two devices for a few seconds. A walk straight through is not reliably seen.

## A witness is silent, or none is listed

1. On that Pi, `journalctl -u radio-sight-witness -n 2 -o cat` shows whether it is signing. After an install or a restart the signing program may need one manual start.
2. If `/chain` lists no witnesses, the board has not read its local key file. If a signature is refused, the public key enrolled on the board is not that Pi's: print it again with `python3 -m pi.witness --pubkey`.
3. Never use `--force`, and never copy a private key off a Pi. The key is made on the Pi and never leaves it.
4. The record keeps counting while a witness is silent, and notes the gap. Say so; do not hide it.

## "What happened?" is slow or wrong

The answer is built from the sealed records, and the small local model only words it. Open the records the answer cites and read from those. If the model is unavailable, the template wording is used; never answer from memory.

## A no-movement alert will not clear

- The still or moving word is steady on purpose and takes a few seconds to change.
- The check-in is to step fully out of the line and back within a few seconds. A lean does not count.
- A check-in or `reset_alert` clears the alert.
- `reset` is the between-judges command; it clears the alert, the still timer, the check-in and the narration.
- While the sensor is blind, decisions are null and the alert timer pauses. Restore a healthy line before testing the alert again.

Use the phrase **no-movement alert** in the demo. It notices sustained stillness, not its cause.

## Proof values show `__`

`__` means the corresponding value in `/proof.json` is still null or unavailable. It is not a failure in the display.

1. Check the proof run for a `missing:` line and collect the named evidence.
2. Keep held-out sessions separate from tuning sessions.
3. Keep the value as `__` until the proof pipeline produces a measured result.
4. Never type an estimate into the page or a public document. The sentences that may be said are in [numbers-to-say.md](numbers-to-say.md).

The Pis run no model. The decision, the alerts, the record and the answers run locally on the UNO Q, on the Dragonwing CPU.

## Return to a known state

Before the next judge:

- plug Pi B back in if it was unplugged, wait for it to rejoin, and set Pi B's clock, which resets whenever it loses power;
- disarm and send `reset`;
- take the baseline with the spot empty;
- confirm health is `ok` and the headline says "Nobody is here";
- confirm both Pis are signing; and
- leave every missing proof result as `__`.
