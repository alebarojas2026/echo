# Team rules for every worker

Radio Sight: **a witness that never watches.** It knows when someone is in a space, keeps a record nobody can edit, and tells you what happened. No camera. No microphone. Nothing sent to the internet.

**This is the final direction (set Sunday 3:30 AM). Anything in an older issue, PR, doc or comment that says otherwise is out of date: follow this file.**

**What it does, in the order a judge sees it:**
1. **It senses a person by radio only.** Two small computers a metre apart: when someone stands between them, their body weakens the Wi-Fi signal. From that one line the board knows someone arrived, whether they are standing still or moving, whether they walked through or stayed, and when they left. Armed, it raises an intrusion; it notices when one of its own devices is unplugged.
2. **It seals what it sensed.** Every record is chained to the one before it (SHA-256), so a changed record breaks every seal after it and the board can name the record.
3. **Two more machines vouch for it.** Each Pi signs the board's latest record every 5 s with its own key. Unplug one and the others carry on and record the gap.
4. **It tells you what happened.** "What happened?" is answered in plain words from the sealed record only, showing its steps and the records it used.
5. **You can watch it work.** A second screen, the engine room, shows the three devices, the record counting up, the signatures arriving and a prove-it check.

- **Who it's for:** places that need a record of who was there and when but cannot have cameras: server rooms and network cabinets, evidence rooms, labs after hours; also restrooms and hotel rooms.
- **The line to build around:** "It can't see you, it can't be edited, and it still tells you exactly what happened."
- **What it does NOT claim:** it does not know who a person is, and it does not know where in a room they are. It senses one spot. Say so plainly; never write "tracks", "locates", "pinpoints" or "which side" about a person.
- **What is cut (do not build, show or write about as part of the product):** the camera and the camera lesson ("taught by a camera" is gone; the webcam is unplugged for judging), any microphone, dead-zone advice and "move the router", two sides and zones along the desk, the ESP32 beacons and far hall beacons, Bluetooth as a sensor (its lines are drawn at most; they decide nothing), location or tracking of any kind. The code for these stays in the repo and old layouts keep working; nothing a judge sees uses them.
- **Why the hardware makes sense:** a building already has Wi-Fi access points and devices on them. Pi A stands in for an access point, Pi B for a device across the room, and the UNO Q (Qualcomm Dragonwing QRB2210) for the chip that would run this inside the access point. Everything runs on the UNO Q; the Pis run no model.

**Re-read this file every time you pull. The "Right now" section is how the team lead redirects everyone.**

## Right now
**Where things stand (Sunday, about 4:15 AM):**
- **`kit-4.2` is tagged (fad7179) and is what the board runs.** One spot, three devices (the board and Pi A side by side on one desk, Pi B across a gap of 85 to 100 cm at desk height). The Wi-Fi line Pi A to Pi B (`pi5>pi5b:wifi`, 25 readings a second, under 1 dB of noise) is the only thing that decides, with NO model, NO lesson and NO camera: after a baseline with the spot empty, the line alone gives the whole decision. Measured on the kit: found on 10 of 10 stands, nothing false in over nine empty minutes, found with Pi B hidden in a backpack, no reaction to someone a metre to the side. A person needs a few seconds on the line (tests use 10-second stands).
- **`kit-5` is being merged: the witness set** (contract issue #866; PRs #870, #871, #873, #874, #872, #877, #878). It goes on the board only after a cold-start check with real recordings and the team lead's word.
- **Every build must pass a cold start before it is tagged:** the real programs started with no model, no baseline and no camera, fed real recordings, with the judge's page looked at. `kit-4` passed every simulated test and failed on the board in the first minute because no test started cold. A reviewer who gates only with a trained or stand-in model has not gated.

**What to work on, in this order:**
1. Review comments and failing checks on your open PRs in the witness set.
2. Open issues titled "Witness: ..." with your tag, then issue #856 (faults on the judge's screen).
3. Fixes for anything the real kit shows (issue #95).
4. Nothing else. No new features, no new feature issues. Old "Hero:", "Wow:", "Desk layout:" and dead-zone issues are out of date: do not pick them up.

**Rules that still hold:**
- **Layout comes from `radio/nodes.json`, never from constants in code.** The demo layout is the gate (`python -m radio.use_layout gate`); it is switched BEFORE the web page is built, because the page carries the layout it was built with as its fallback.
- **Hands-on hardware is Alexander's and Ivan's laptop session's** (issue #95). When a task needs the real devices, comment `needs Alexander:` on the issue with exact commands and what to look for, then take your next issue. A baseline with the spot empty is the first step after every deploy.
- Lanes: advisor/ is Izet's; narrator/ and teacher/ are Alejandro's; radio/, pi/, board/, bus/ and mcu/ are worked by the lead's workers (Alexander is on hardware).
- **CI is down (the account's Actions limit), so a red check means nothing right now.** The merge gate is a local run: check out the PR merged with current main in a clean folder, run that lane's tests (pytest for the folder and `python -m pytest contracts`; for web: `npm ci && npx tsc --noEmit && npx vitest run && npx vite build`) with the desk layout AND with the gate active, and write the result in a PR comment ("CI unavailable; local: N passed"). Don't push empty commits to re-run CI.
- **GitHub's API limit was hit tonight.** Read code and diffs with git (fetch the branches). Use `gh` only to open PRs and issues, comment and merge.
- **Times:** Sunday 8:00 AM, last merge that touches anything a judge sees or the board runs. 9:30 AM, the board is frozen on a tagged commit; after that only a rollback to the previous tag goes on it. 10:30 AM, Devpost is submitted. One person deploys and a second checks it; every deploy ends with the baseline, the device checks and a look at the screen.
- Simulated results are never written as measured. Numbers in the pitch, the screen and Devpost come from PROOF.md only.

## Lanes (stay in yours)
| Tag | Folders | Owner |
|---|---|---|
| room | web/src/room/, web shell (web/index.html, web/src/main.ts, web/package.json) | Ivan |
| hud | web/src/hud/, web/tests/, scripts/ | Ivan |
| radio | radio/, pi/ | Alexander |
| advisor | advisor/ | Izet |
| board | board/, mcu/, bus/ | Alexander |
| brain | brain/ | Izet |
| teacher | teacher/ | Alejandro |
| proof | proof/, PROOF.md | Izet |
| sim | sim/ | Alejandro |
| docs | docs/, web/src/game/ | Alejandro |
| narrator | narrator/ | Alejandro |

CONTRACTS.md, contracts/, AGENTS.md, CLAUDE.md and README.md are changed only by Ivan. Need a format change? Open an issue labeled `contract` and keep going with the current format.

## Work loop
1. Run `git pull --rebase origin main` and re-read this file.
2. Check your open PRs for review comments (`gh pr list --author @me`, then `gh pr view <n> --comments`). Do the requested fixes first.
3. Run `gh issue list --state open --label <your tag> --json number,title,body,comments`. Take the lowest-numbered issue nobody has commented `taking` on, and comment `taking`.
4. Build it on its own branch (a plain name, never a tool name), with tests:
   - commit every 15-20 minutes and push every time;
   - open a PR with `Closes #<number>` in the body, under 600 lines;
   - don't wait for review; go back to step 1.
5. If a task needs hardware or a person, comment exactly what's needed on the issue, then take the next one.
6. No issues left with your tag? Add tests for what exists, then stop and say so on issue #95. Don't open new feature issues (the freeze, "Right now" item 9).

## Style (every screen: room, HUD, game page)
**The look (Ivan's pick): a pro, technical instrument, as clean as a Tesla car screen.** The 3D room is the hero. Very little text, each piece of it large and certain. Dark background. People are simple, faceless 3D figures.

Colours: each one means one thing and nothing else.
- Page and canvas #111316. Floor and cards #1A1D21. Edges and lines #353B43. The sensing square's outline #6B7480.
- Text #E6E8EB. Secondary text #9AA3AD.
- link #858E99: a healthy radio link. Neutral on purpose: only the links behind the decision turn person amber.
- person #FF9F43: the one accent. The person (the figure, the X-ray heat up to #FFD29A, the links behind the decision, zone names).
- object #A9B4C2: objects (hatching, markers).
- action #34B277: the router advice arrow and the check-in.
- fault #F2555A: a broken link and the no-movement alert.
- Green and red are status only, and always come with a word ("Wave seen", "No movement", "no signal"). Never colour alone.
- Take colours from the shared tokens (web/src/room/palette.ts and the CSS variables), never a hard-coded hex.

Type: Hanken Grotesk only (self-hosted in web/src/hud/fonts/). No serif.
- One headline per moment, built from the state (instant, never waits on the narrator): 600 weight, 56-84 px. Examples: "Still in the bathroom", "An object, not a person", "Nobody is here".
- Anything a judge needs to read is at least 28 px. Numbers use tabular figures.
- Plain words, never ids on screen: "East to UNO Q, Bluetooth", not east>unoq:ble.
- Operator controls and debug values are hidden from judges (shown with the O key or ?op=1).

Motion: calm and meaningful, opacity and transform only.
- Text changes: old text out in 100 ms, new text in over 140 ms starting 40 ms later, in the same spot. Nothing jumps or reflows.
- The person moves only once a new zone has held for 200 ms, then glides (critically damped, about 650 ms, no overshoot). Nothing teleports.
- No loops, pulses, glow, bloom, gradients, purple, emoji or neon; no pure black or pure white.

## Hard rules
- **Open every PR against main.** Never base a PR on another PR's branch: when that branch merges and is deleted, your PR closes. If you need unmerged work, wait for it to merge, or build against main with a small stub.
- **No images or video, ever.** Never write a camera frame to disk. Never commit image or video files (test screenshots in web/tests/ are the only exception).
- **No secrets or device identifiers in the repo.** No passwords, keys, MAC addresses, BSSIDs, personal device names, or IP addresses other than the ones in CONTRACTS.md. Local values go in `.env` (gitignored).
- **No invented numbers.** Every number on screen or in docs is measured and has a PROOF.md row. Until then it is left off the judge-facing screen (its proof tile isn't drawn), and shown as `__` anywhere it has to appear (PROOF.md, proof.json's null, the docs).
- **Commit and PR text are plain and human.** No Co-authored-by lines, no "Generated with", no session links, and no tool or AI names in commits, PR titles or bodies, branch names or code comments.
- **Words:**
  - say "no-movement alert", never "fall detection";
  - say "works behind a curtain", never "sees through walls";
  - say "safety and after-hours security" and "presence and intrusion detection". Never say it identifies who someone is, counts a crowd, or is "surveillance";
  - never say "NPU" (this chip has none; say "on the Dragonwing CPU").
- **All AI runs on the UNO Q.** The Pi runs no model. Use our own network only and never the venue Wi-Fi.
- No prewritten code. Libraries are fine. Open-source sensing projects are for reading only, never copied.

## Hardware facts (don't relearn these the hard way)
- **UNO Q:**
  - Debian on 4x Cortex-A53 with 4 GB RAM and no NPU.
  - Wi-Fi uses the ath10k driver: no monitor mode, no CSI.
  - Bluetooth 5.1.
  - Logic is 3.3 V.
  - onnxruntime crashes on it, and PyTorch is too heavy. Use scikit-learn.
- **App Lab:**
  - App Lab runs apps in Docker containers on their own network. Only the camera teacher (teacher/applab/) runs there.
  - Everything else runs as host systemd services (CONTRACTS.md section 9).
  - From inside App Lab, the bus is at `msgpack-rpc-router:5600`.
- **Bridge:** a host Python process calls the microcontroller through the `arduino` package. It's a wheel from the github.com/arduino/app-bricks-py releases, not on PyPI.
  - Flash the LED sketch with `arduino-cli compile --fqbn arduino:zephyr:unoq --upload mcu/`.
- **Bluetooth:**
  - bleak's default filters duplicates, which gives about one reading per beacon. Use a raw HCI scan as root, with duplicate filtering off, confirmed in btmon ("Filter duplicates: Disabled").
  - Match beacons by advertised data, never by MAC.
- **Network:**
  - The Pi's 5 GHz hotspot is the sensing link. The board joins it locked to the Pi's BSSID, with power saving off.
  - The Pi (192.168.77.1) and the board's hub (192.168.77.2) are joined by ONE Ethernet cable. It carries the Pi's Bluetooth readings and the page data, so they never depend on the Wi-Fi link we block on purpose in the demo.
  - The demo screen is a laptop's browser (no monitor, no Pi kiosk, no switch). The laptop joins the Pi's hotspot and opens http://192.168.77.2:8080/ (live is the default; the engine room is /engine/); the Pi forwards it to the board over the cable. Only light traffic may use the hotspot while the model runs: never copy files or bundles over it during a demo or a recording (it can starve the sensing link and show SENSOR BLIND).
  - The board has no internet once it is on the hotspot. Install things before it joins.
- **The demo layout (the gate, `radio/layouts/gate.json`):**
  - One spot. The board and Pi A side by side on one desk (they share the hub, about 8 cm apart); Pi B across a gap of 85 to 100 cm, at desk height. On a chair seat it fails (0 of 5): keep it at desk height.
  - Pi B has no cable. It joins Pi A's hotspot and sends its readings to 192.168.77.2:5600 through Pi A. Never run `pi/install.sh --wifi-off` on Pi B: that takes the only sensor down.
  - Only `pi5>pi5b:wifi` decides. The Bluetooth lines dip 9 to 20 dB with nobody there and the 8 cm desk line drifts: neither can make the sensor blind, raise an object, or vote.
  - The old desk strip (five nodes, two zones, ESP32 beacons on arms) is still a valid layout file for tests and is not used in the demo.
- **No tape until the presentation hour.** During the build, the layout is measured and marked with loose markers. In the presentation room it gets taped, and the calibration, the 20 s baseline and the training are redone there. Never write instructions that assume tape is already on the floor.
- **Phones as beacons:** they top out at about 10 adverts a second. ESP32s can go faster.
