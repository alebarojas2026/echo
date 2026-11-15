# Team rules for every worker

Echo: **a witness that never watches.** It knows when someone is in a space, keeps a record nobody can edit, and tells you what happened. No camera. No microphone. Nothing sent to the internet.

**This is the final direction (set Sunday 3:30 AM). Anything in an older issue, PR, doc or comment that says otherwise is out of date: follow this file.**

**What it does, in the order a judge sees it:**
1. **It senses a person by radio only.** Two small computers a metre apart: when someone stands between them, their body weakens the Wi-Fi signal. From that one line the board knows someone arrived, how long they stayed, whether they are standing still or moving, and when they left. Armed, it raises an intrusion; it notices when one of its own devices is unplugged.
2. **It seals what it sensed.** Every record is chained to the one before it (SHA-256), so a changed record breaks every seal after it and the board can name the record.
3. **Two more machines vouch for it.** Each Pi signs the board's latest record every 5 s with its own key. Unplug one and the others carry on and record the gap.
4. **It tells you what happened.** "What happened?" is answered in plain words from the sealed record only, showing its steps and the records it used.
5. **You can watch it work.** A second screen, the engine room, shows the three devices, the record counting up, the signatures arriving and a prove-it check.

- **Who it's for:** places that need a record of who was there and when but cannot have cameras: server rooms and network cabinets, evidence rooms, labs after hours; also restrooms and hotel rooms.
- **The name is Echo** (decided Sunday 4:30 AM). Everything a judge reads says Echo: the screen's title, the engine room, the phone page, the docs, Devpost. "Radio Sight" is the old name. Internal names stay as they are (the `radio-sight-*` units, `RADIO_SIGHT_*` variables, folder names): do not rename code.
- **The line to build around:** "It can't see you, it can't be edited, and it still tells you exactly what happened."
- **What it does NOT claim:** it does not know who a person is, and it does not know where in a room they are. It senses one spot. Say so plainly; never write "tracks", "locates", "pinpoints" or "which side" about a person.
- **What is cut (do not build, show or write about as part of the product):** the camera and the camera lesson ("taught by a camera" is gone; the webcam is unplugged for judging), any microphone, dead-zone advice and "move the router", two sides and zones along the desk, the ESP32 beacons and far hall beacons, Bluetooth as a sensor (its lines are drawn at most; they decide nothing), location or tracking of any kind. The code for these stays in the repo and old layouts keep working; nothing a judge sees uses them.
- **Why the hardware makes sense:** a building already has Wi-Fi access points and devices on them. Pi A stands in for an access point, Pi B for a device across the room, and the UNO Q (Qualcomm Dragonwing QRB2210) for the chip that would run this inside the access point. Everything runs on the UNO Q; the Pis run no model.

**Re-read this file every time you pull. The "Right now" section is how the team lead redirects everyone.**

## Right now
**Status, Sunday 9:10 AM. Written by the team lead for every worker; Alejandro's worker, your list is at the end of this section.**

**9:10 AM: the board is finished and frozen.** It runs the `kit-5.1` programs with the object rule off (the layout number in `kit-5.1.1`), its services read the Central time zone (one line in the board's local settings file, so clock times in answers are right), and it serves the `kit-5.2.1` page (0eaf8c9): the hall fills the judge's page, the engine room is one picture of the sealed record, titles are Tenor Sans and text is Poppins, the alarm page says "at the desk". All of it was looked at on the real kit. Nothing more goes on the board. Only `docs/`, `proof/` and PROOF.md may change, until 10:30 AM.

**What is left is not code:** a demo video of 3 minutes or less (the organisers said sponsor tracks require one), the Devpost page (gallery pictures from the real kit, all four teammates attached), three rehearsals of the round, and setting up at the judging desk. The organisers' rule for this track: all processing is done on the UNO Q. Say it that way: every decision, every record and every answer is computed on the UNO Q; the Pis make the signal, measure it and countersign. Never write "a record of who was there": Echo does not know who. Write "a record of when someone was there".

**What is on the kit**
- **`kit-5` (c79da9b) is tagged and running on the board and both Pis.** It is the witness set on top of `kit-4.2`: the sealed record, the two Pis signing it, "What happened?" from the record, the engine room.
- **Checked on the real kit this morning, one person** (the step-by-step results are on issue #95):
  - 10 of 10 ten-second stands, "Someone is here" within about 0.1 s of the body reaching the line; two empty minutes with nothing false.
  - The no-movement alert at 10 s of standing still; stepping aside and back gave the check-in and cleared it.
  - Armed: one intrusion on one stand; the report came back in 0.6 s.
  - "What happened in the last five minutes?" answered in 0.1 s with clock times.
  - Both Pis signing with good signatures. Prove it altered record 1627 in a copy and the check named 1627; the real record still verified.
  - Pi B unplugged: shown silent within 14 s, back by itself, the record kept rising and stayed verified.
- **So this is now true and may be said:** the sealed record and the signing have run on the real board. Numbers for the pitch, the screen and Devpost still come only from PROOF.md and `docs/numbers-to-say.md`; the run above is not in them until the proof worker adds it.
- **Not checked by eye on the kit yet:** the engine room page.

**What is final, and the one thing still being built**
- **`kit-5.1` (4be0eea) is tagged. It is the FINAL software for the board and both Pis.** Nothing under board/, brain/, bus/, pi/, radio/, store/, narrator/, the agent or contracts/ merges again today, whatever it fixes. It is `kit-5` plus only these: the accent is blue #1FA5CF (#897); a "What happened?" button on the judge's page (#899); a "Sealed record · verified · 2 witnesses" line (#902); placing the screen by clicking the desk the kit is on (press P, click the desk, G for the other side, Enter saves; #901); the name Echo everywhere a person reads it (#906); the alarm page's hint says step aside and back (#903); "was anyone here" shows its steps and records (#904); the narrator never contradicts the headline (#905); a chain check beside a prune cannot give a false alarm (#907); and a fix from the kit, a wave on another link is no longer a check-in on the one spot (#909). It passed every lane on Linux on both layouts and a cold start with the kit's recordings. Ivan deploys it (about 10 minutes, no keys to make; steps on #95). If anything looks wrong the devices go back to `kit-5`.
- **`kit-5.2` is the page only (web/ and docs/), approved by Ivan at 6:55 AM, and is the only thing still being built:** the judge's page with the hall filling the whole screen and the text on it (branch `judge-page-hall-first`), the engine room as one picture of the sealed record instead of a card grid (branch `engine-room-one-picture`), and a new font (Poppins for text; the title face is being chosen; Hanken Grotesk goes). It reaches the board by `board/push-web.sh` alone: no deploy, no restart, no baseline; `board/push-web.sh --back` undoes it. It goes on only if it is reviewed safe by 9:00 AM; otherwise the page stays as `kit-5.1` has it. A PR for it that touches anything outside web/ and docs/ is out.
- **Known and left alone on purpose:** when Pi B is unplugged, Pi A can be shown silent for about 4 s (two late signatures against a 15 s limit) and then recovers. The fix waits until after the demo.
- Besides `kit-5.2`, only `docs/`, `proof/` and PROOF.md may change, until 10:30 AM.

**What comes next, in order**
1. `kit-5.1` on the kit: baseline, one stand, the blue, P to place the stand, both Pis still signing, the engine room looked at by eye.
   Then the `kit-5.2` page push by the lead, if it is safe, and a look at both pages on the kit.
2. Each screen laptop joins the kit's own Wi-Fi and opens its page: the judge's page `http://192.168.77.2:8080/`, the engine room `/engine/`, the alarm page `/phone/` on a phone.
3. Three rehearsals of the 3-minute round at the desk.
4. Devpost page and video; Ivan submits by 10:30 AM. Judging is 1:00 to 3:00 PM, three minutes a desk.

**The judge's part of the demo (this is the order; no walk-through anywhere):** step in and stand (the figure appears); stand still until the no-movement alert, then step aside and back (check-in); armed, step in (intrusion); ask "What happened?"; press Prove it on the second screen. Nobody unplugs a Pi in the round: on the kit that step moved Pi B and cost the margin (7:10 AM). The silent witness is said in one sentence, not performed.

**Seen on the kit, worth knowing**
- Pi B's clock resets every time it loses power, and its cable came out once: secure the power cable, and set the clocks after any power-up, before the baseline.
- After the install, Pi B's signing program needed one manual start. Check it is running on each Pi after any restart.
- A small nudge of one device costs the margin: after Pi B's cable was pulled a person took 9 to 11 dB off the line where the same stand took 12 to 17 dB before. Place the kit once, tape Pi B and its cable, and check before each session: the empty line about -44 dBm or better and a person on the spot 12 dB or more.
- **`kit-5.1.1` (8468217) is tagged: the object rule is off on the one spot** (#916). A very still person at 9 to 10 dB was being called "something left in the line", with no alert and no check-in. Nothing on the one spot is called an object now; never write that Echo tells a thing from a person. The board runs kit-5.1 with this one layout number changed, which is the same thing.
- When Pi B was unplugged, Pi A was shown silent for about 4 s though nobody touched it, then recovered. Do not write "the others never miss a beat".

**Decisions made this morning that a worker must not undo**
- The architecture pictures carry plain titles ("Architecture", "Data path"): no tagline, no "no internet, no camera, no microphone" banner, no "what it does not do" note on the pictures. Do not add them back to `docs/architecture.svg`.
- The accent is blue #1FA5CF, not orange. Screenshots in docs that still show orange are old.
- The font is changing (Ivan, 7:00 AM): Poppins for text and an elegant title face. Do not write "Hanken Grotesk" into new docs; the Style section below is updated when the face is chosen.
- Screens at the stand join the kit's own Wi-Fi. There is no public web link.
- No backups or spare plans in docs: one way of doing each thing.

**Rules that still hold**
- **Every build passes a cold start before it is tagged:** the real programs started with no model, no baseline and no camera, fed real recordings, with the judge's page looked at.
- **Layout comes from `radio/nodes.json`.** The demo layout is the gate (`python -m radio.use_layout gate`), switched BEFORE the web page is built.
- **Hands-on hardware is Alexander's and Ivan's laptop session's** (issue #95). A baseline with the spot empty is the first step after every deploy and every power-up.
- **CI is down**, so a red check means nothing. The gate is a local run on both layouts, written in a PR comment ("CI unavailable; local: N passed").
- **GitHub's API limit was hit last night.** Read code and diffs with git. Use `gh` only to open PRs and issues, comment and merge.
- Simulated results are never written as measured.

**For Alejandro's worker (lanes: docs/, web/src/game/, narrator/, teacher/, sim/)**
Only `docs/` from now on; leave narrator/, sim/, teacher/ and web/src/game/ alone unless the lead asks on an issue. One small PR per file, tests in `docs/` passing, in this order:
1. **`docs/demo-runbook.md`** is the most out of date: it still has a camera-unplug proof, a camera cable handed over and training. Rewrite it for the round above: no camera, no lesson, baseline only; the judge's part exactly as listed; the pages and their addresses; P to place the screen at the stand (the card text is in the body of PR #901); clocks after power-up; Pi B's power cable; going back is one command per device (on #95).
2. **`docs/devpost-draft.md`** (issues #687 and #879): the final direction, the name Echo, "What runs on the UNO Q", the sentences from `docs/numbers-to-say.md` word for word, no blanks, working links, the two architecture pictures.
3. **`docs/pitch.md`, `docs/judge-faq.md`, `docs/video-shots.md`** (issue #879): the same direction and the same round; the FAQ answers "what exactly runs on the chip?" and "what breaks it?" plainly (a walk straight through is not reliably seen; a person needs a few seconds on the line; one spot; placement matters).
4. **`docs/build.md`, `docs/network.md`, `docs/troubleshooting.md`** (issue #852): three devices and one spot, not the five-device desk strip; the signing set-up on each Pi (the key is made on the Pi and never leaves it; only the public key goes in the board's local key file).
Never write: tracks, locates, pinpoints, counts people, sees through walls, blockchain, unhackable, tamper-proof, "performs radio tomographic imaging" (allowed: "built on the physics behind radio tomographic imaging, on a single link"), a walk-through being detected, or any number that is not in `docs/numbers-to-say.md`. When done or stuck, say so in a comment on issue #879.

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
- link #858E99: a healthy radio link. Neutral on purpose: only the links behind the decision turn person blue.
- person #1FA5CF: the one accent (blue). The person (the figure, the X-ray heat up to #A6E0F2, the same blue lighter; the links behind the decision, zone names).
- object #A9B4C2: objects (hatching, markers).
- action #34B277: the router advice arrow and the check-in.
- fault #F2555A: a broken link and the no-movement alert.
- Green and red are status only, and always come with a word ("Wave seen", "No movement", "no signal"). Never colour alone.
- Take colours from the shared tokens (web/src/room/palette.ts and the CSS variables), never a hard-coded hex.

Type: two faces, both self-hosted in web/src/hud/fonts/. Titles are Tenor Sans at 400 (it has no bold: never ask for one). All other text is Poppins. Take the family from the tokens in web/src/hud/tokens.css (`--font-title`, `--font-text`); never name a typeface in a page. No serif.
- One headline per moment, built from the state (instant, never waits on the narrator): 400 weight, 56-84 px. Examples: "Still in the bathroom", "An object, not a person", "Nobody is here".
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
