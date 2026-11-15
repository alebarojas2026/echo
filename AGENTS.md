# Team rules for every worker

Radio Sight: safety and after-hours security for buildings, using the Wi-Fi that's already there. No cameras.

- **Who it's for:** places where cameras can't go or aren't wanted (patient rooms, bathrooms, study rooms, offices after hours). It knows someone is in a space, where, and whether they've been still too long, and it tells someone when a space that should be empty isn't.
- **What's new:** a camera teaches the radio in seconds, on the board, and is then unplugged. "Taught by a camera. Runs without one." Nothing leaves the board.
- **Why the hardware makes sense:** a building already has Wi-Fi access points every 10-15 m. Our Pi stands in for one, the UNO Q (Qualcomm Dragonwing QRB2210) stands in for the chip inside it, and the beacons stand in for the other radios a building already has. Only the webcam is extra, and only for teaching.
- **Two scales on one screen:** one space in detail (the sensing area at our desk) and the whole building in outline (the hall model with long "movement on this path" links).
- Everything runs on the UNO Q. The Pi is the router and runs no model. The screen is any browser on our own network.

**Re-read this file every time you pull. It changes during the event, and the "Right now" section is how the team lead redirects everyone.**

## Right now
The direction above is new (Saturday evening). Priorities, in order:
1. **Real measurements beat everything.** Nothing has run on the real hardware yet. Anything that helps tonight's hardware tests pass and puts measured numbers in PROOF.md comes first.
2. **The hero path:** a judge steps up and is found ("Found you. 0 cameras."); the camera teaches the radio on the judge in about 30 s; the camera is unplugged and it still follows them, even standing still; armed mode raises an intrusion alert on the phone page; the judge asks the room a question and the board answers from its own records. Issues titled "Hero: ..." are this path and come before other issues in your lane.
   Added Saturday night, same priority (issues titled "Wow: ..."; wording to build against is in contract issue #533): a tamper alert when a device is unplugged while armed (#534), a replay of what the room recorded, from the board's records (#535, #537), a live signal trace that dips when someone steps in (#536), and an incident report after an armed stretch (#535, #537).
3. Work from GitHub issues with your tag, using the loop below. Don't wait for a person. Fix review comments on your open PRs before starting new work.
4. **Layout:** take node positions, links and zones from radio/nodes.json, never from constants in code. The layout is moving from the 2 x 2 m square to a strip in front of a desk (draft PR #415).
5. **Hands-on hardware is Alexander's and Ivan's laptop session's** (issue #95). When a task needs the real devices, comment `needs Alexander:` on the issue with exact commands and what to look for, then take your next issue.
6. Not in the 3-minute demo any more (don't polish them): the crowd game, the tray and router-advice beat, the recap. They stay working for the finalist round and questions.
7. Lanes: advisor/ is Izet's; narrator/ and teacher/ are Alejandro's; radio/, pi/, board/, bus/ and mcu/ are worked by the lead's workers (Alexander is on hardware).
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
  - The demo screen is a laptop's browser (no monitor, no Pi kiosk, no switch). The laptop joins the Pi's hotspot and opens http://192.168.77.2:8080/?src=ws ; the Pi forwards it to the board over the cable. Only light traffic may use the hotspot while the model runs: never copy files or bundles over it during a demo or a recording (it can starve the sensing link and show SENSOR BLIND).
  - The board has no internet once it is on the hotspot. Install things before it joins.
- **No tape until the presentation hour.** During the build, the layout is measured and marked with loose markers. In the presentation room it gets taped, and the calibration, the 20 s baseline and the training are redone there. Never write instructions that assume tape is already on the floor.
- **Phones as beacons:** they top out at about 10 adverts a second. ESP32s can go faster.
