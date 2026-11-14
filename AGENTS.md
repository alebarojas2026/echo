# Team rules for every worker

Radio Sight: Wi-Fi that understands the room. Radio links between 4 nodes around a 2 x 2 m floor square show where a person is, whether they're moving, and what's an object vs a person. Everything runs on an Arduino UNO Q (Qualcomm Dragonwing QRB2210). A Raspberry Pi 5 is the router and runs no model. The screen is any browser on our own network.

**Re-read this file every time you pull. It changes during the event, and the "Right now" section is how the team lead redirects everyone.**

## Right now
1. CONTRACTS.md v2 is final. Switch your adapter to it before anything else.
2. Work from GitHub issues with your tag, using the loop below. Don't wait for a person.
3. Fix review comments on your open PRs before starting new work.
4. **All hands-on hardware is Alexander's.** That means the board, the Pi, the webcam, the phones, tape, mounting and flashing. When a task needs it, comment `needs Alexander:` on the issue with the exact commands and what to look for, then take your next issue. Never ask Izet, Ivan or Alejandro to do hardware.
5. **Alexander's workers: pause now.** At your next clean checkpoint, finish the commit you're on, push your branch, and post ONE comment on your open PR (or the issue you took) listing what's done, what's left, and anything half-finished. Then stop: take no new issues and open no new PRs. The radio, pi, board, bus and mcu lanes are being handed to other workers, who will build on what you pushed. Alexander keeps all the hands-on hardware (issue #95).
6. Brain: #220 (the still timer) and #222 (SENSOR BLIND on the tray) come before every other brain issue. They decide whether the no-movement alert and the tray beat work in the demo.
7. Lanes moved: advisor/ is now Izet's (Alexander is on hardware full time); narrator/ and teacher/ are now Alejandro's. Take those tags too.

8. **CI is down (the account's Actions limit), so a red check means nothing right now.** Until it's back, the merge gate is a local run: check out the PR merged with current main in a clean folder, run that lane's tests (pytest for the folder and `python -m pytest contracts`; for web: `npm ci && npx tsc --noEmit && npx vitest run && npx vite build`), and write the result in a PR comment ("CI unavailable; local: N passed"). Don't push empty commits to re-run CI.

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
6. No issues left with your tag? Add tests, then open a new issue with your tag for the most useful next step and do it.

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
- **No invented numbers.** Every number on screen or in docs is measured and has a PROOF.md row. Until then, show `__`.
- **Commit and PR text are plain and human.** No Co-authored-by lines, no "Generated with", no session links, and no tool or AI names in commits, PR titles or bodies, branch names or code comments.
- **Words:**
  - say "no-movement alert", never "fall detection";
  - say "works behind a curtain", never "sees through walls";
  - say "room-aware", never "security system";
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
  - The demo screen is a laptop's browser (no monitor, no Pi kiosk, no switch). The laptop joins the Pi's hotspot and opens http://192.168.77.2:8080/?src=ws ; the Pi forwards it to the board over the cable. Only light traffic may use the hotspot while the model runs: never copy files or bundles over it during a demo or a recording (it can starve the sensing link and show SENSOR BLIND).
  - The board has no internet once it is on the hotspot. Install things before it joins.
- **No tape until the presentation hour.** During the build, the layout is measured and marked with loose markers. In the presentation room it gets taped, and the calibration, the 20 s baseline and the training are redone there. Never write instructions that assume tape is already on the floor.
- **Phones as beacons:** they top out at about 10 adverts a second. ESP32s can go faster.
