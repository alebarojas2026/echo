# Radio Sight: Pitch and Presentation Game Plan

This is the plan for the hours from now to the last judge. The words to say are in [pitch.md](pitch.md), the operator steps in [demo-runbook.md](demo-runbook.md), the answers in [judge-faq.md](judge-faq.md) and the video in [video-shots.md](video-shots.md). This page says **who does what, when, and what we do when something breaks.**

Every result stays `__` until it has a [PROOF.md](../PROOF.md) row. Times we have not confirmed with the organisers are also `__`.

## What a judge must leave with

If a judge remembers only three things, they are these:

1. **Radio Sight can tell a person from a tray.** The radio links already in a room show where a person is, whether they are moving, and what is an object instead.
2. **It all runs on the UNO Q.** Training and every decision happen on the Dragonwing CPU. The Pi is only the router. The camera is unplugged during the demo.
3. **It is useful.** It finds a real dead zone and tells you where to move the router, and it raises a no-movement alert that a wave clears.

Every sentence we say should support one of these three. If it doesn't, cut it.

## Track fit

| What the Qualcomm / N+1 track wants | Where the judge sees it |
|---|---|
| Real AI on the edge device | Training and live predictions on the UNO Q's Dragonwing CPU; the proof strip shows time to train and time per decision |
| Using the board, not just a laptop | The LED grid on the UNO Q, the camera on the UNO Q, the web page served by the UNO Q |
| A working, complete build | One unbroken live run: judge walks in, through to the proof strip |
| Theme "Let's Dig In" | We dig into the signal already in the room instead of adding sensors |
| Honesty about results | Held-out numbers with their method, `__` where we have none, and the honest limits |

## Roles on the day

Default assignment. Swap names here if the team decides otherwise, but one person holds each role for the whole event so nobody hesitates.

| Role | Person | Does | Never does |
|---|---|---|---|
| Speaker | Alejandro | Says the pitch, invites the judge into the square, points at the screen | Touches the laptop or the hardware mid-demo |
| Operator | Ivan | Runs the laptop, watches health, sends `router_moved`, `router_home` and `reset` with the operator view (O key) | Speaks over the speaker; shows the operator view to judges |
| Hardware | Alexander | Places the tray, moves the router, unplugs the camera, fixes cables and power | Explains the model (hands that question to Izet) |
| Proof | Izet | Answers accuracy, model and timing questions; keeps PROOF.md current; reads `/proof.json` if asked | Gives a number that is not in PROOF.md |

**Hand-off line.** When a question belongs to someone else, the speaker says "Izet built the model, Izet?" and steps back. No one answers a question outside their lane with a guess.

## Timeline

Wall-clock times are `__` until the organisers publish the schedule. Fill them in the moment we know.

| When | Gate | Done when | Owner |
|---|---|---|---|
| Now | G1: the story runs on simulation | `python -m sim.rehearse` passes every beat | Alejandro |
| Now | G2: pitch timed | The 90-second pitch is said out loud, timed, by the speaker, three times in a row without notes | Alejandro |
| `__` | G3: one live run | The whole demo sequence runs once, live, on real radio, in the build space | Alexander with Ivan |
| `__` | G4: proof measured | Every number the pitch says has a PROOF.md row, or the pitch keeps `__` and we stop chasing it | Izet |
| `__` | G5: video recorded | The 60-second video from video-shots.md is recorded on a live run, not a replay | Alejandro with Alexander |
| `__` | G6: Devpost submitted | devpost-draft.md is pasted in with the video link, and the numbers match PROOF.md | Alejandro |
| `__` | G7: feature freeze | Only fixes after this point. No new beats, no new screen text | Everyone |
| Presentation hour | G8: room set up | The presentation-room setup below is done and `scripts/demo-check.sh` passes | Alexander with Ivan |
| Presentation hour | G9: dress rehearsal | One full run in the presentation room, timed, with a teammate as the judge | Everyone |

**Rule:** if G3 isn't green by the time G7 arrives, we cut beats (see the fallback ladder) instead of adding fixes.

## Presentation-room setup

Tape goes down only here, in the presentation hour. Everything before this uses loose markers. In order:

1. **Lay out (Alexander).** Tape the 2 x 2 m square and its four zone corners (Bed, Chair, Hall, Bathroom). Tape the router spots S-home, S-W30, S-E30 and the tray spot T1. Put the nodes on their stands at their marks.
2. **Cable and power (Alexander).** Run the one Ethernet cable from the Pi to the board's hub. Keep every cable outside the square.
3. **Screen (Ivan).** The laptop joins the Pi's hotspot and opens `http://192.168.77.2:8080/?src=ws`. Check that the source badge says `live`.
4. **Check (Ivan).** Run `scripts/demo-check.sh`. Fix the first failure, then run it again.
5. **Calibrate and baseline (Ivan, square empty).** Redo calibration and the 20 s baseline here. Everyone stays out of the square. Wait for `baseline_done`.
6. **Train (Ivan, with the camera on).** Walk every zone while the camera teacher labels. Wait for `trained`.
7. **Dress rehearsal (everyone).** One full run with a teammate as the judge. Time it.
8. **Reset (Ivan).** Tray off, router on S-home, `router_home`, `reset`. Wait until health is `ok`.

Time this setup in the build space before the day. Write the measured time here: `__`. Start the setup at least that long before the first judge, plus a margin.

**During a demo nothing else uses the hotspot.** No file copies, no bundle uploads and no phone hotspots near the square. That load can starve the sensing link and show SENSOR BLIND.

## Three lengths of pitch

Judges give us different amounts of time. Know all three cold.

### 10 seconds (someone walking past)

> Your Wi-Fi can't tell a person from a tray. Radio Sight can. Step into the square and watch the screen.

### 30 seconds (a judge stops at the table)

> This is Radio Sight: Wi-Fi that understands the room. Four radio nodes around this square measure the links between them. A model we trained on this Arduino UNO Q reads those links and knows where you are, whether you're moving, and whether a change is a person or an object. The camera only taught it during setup, and now it's unplugged. Want to try? Step into the square.

### 90 seconds (the full demo)

Use [pitch.md](pitch.md) exactly as written. It follows the demo order: judge walks in, radio X-ray, no-movement alert, wave check-in, tray vs person, router advice, camera unplug, proof strip.

### Longer slot (stage or finalist round)

Open with the 30-second version, run the full demo, then spend the rest on how it works (the radio X-ray, the camera teaching the model, training on the board) and on the honest limits. End on the proof strip and the one-line close: "Radio Sight. Wi-Fi that understands the room."

## Demo choreography

**Where people stand.**
- The speaker stands outside the square on the screen side, so the judge, the square and the screen are in one view.
- The operator sits at the laptop, turned so the judge sees only the judge view.
- Alexander stands by the router and tray marks, outside the square.
- Everyone else stays well clear of the square and the links. A teammate standing near a link changes the reading.

**The beats, with the line that invites the judge:**

| Beat | Judge does | Speaker says (lead-in) | Screen should show | If it doesn't |
|---|---|---|---|---|
| Walk in | Steps into the square | "Step in and walk to any corner." | A moving person and the zone name | Wait a breath. Ask them to walk to another corner. Never explain it away |
| Radio X-ray | Nothing | "These are the links your body just changed." | The person's heat and the amber links behind it | Skip to the next beat |
| No-movement alert | Stands still in the Bathroom corner | "Now stand completely still for a moment." | The no-movement alert | After the zone's limit plus a few seconds, move on: "the timer needs a clean still, let's check in instead" |
| Wave check-in | Waves back and forth without leaving the zone | "Wave like this." (the speaker shows the practised wave) | "Wave seen" and the alert clears | Operator sends `reset`; say "the reset control does the same" |
| Tray vs person | Steps out of the square | "Now watch: this is a metal tray, not a person." | "An object, not a person" | Name it honestly: "it's still deciding". Don't wait more than a few seconds |
| Router advice | Watches | "It knows which link the tray broke, and where the router should go." | The advice arrow, before value | Skip; go to the camera unplug |
| Move router | Watches Alexander move it | "Let's do what it says." | The after value | Show the before value and say the after value is still settling |
| Camera unplug | Watches Alexander pull the cable | "The camera only taught it. Now it's gone." | Camera off, radio still live | Keep going. The cable in the hand is the proof |
| Proof strip | Reads | "Every number here is measured. Blank means we haven't measured it yet." | The proof strip | Read out the rows from PROOF.md |
| Reset | Leaves | "Thank you." | Nobody is here | Operator follows "Finish the live demo" in the runbook |

**Practise the wave** until every teammate does it the same way, so the speaker can show it and the judge can copy it.

## Fallback ladder

Go down one rung at a time. Say out loud which rung we are on. **A replay or a video is never called live.**

1. **Full live demo.** All the beats.
2. **Short live demo.** Drop router advice and the router move (they take the longest and depend on the tray). Keep walk in, X-ray, check-in, tray vs person, camera unplug, proof.
3. **Core live demo.** Walk in and X-ray only, while the operator fixes the rest. This is the minimum that still proves radio-only sensing.
4. **Recorded session.** Replay a real recorded session with `python -m sim.replay`. The source badge says replay; the speaker says "this is a recording of a live run from earlier today".
5. **Video.** Play the 60-second video on the laptop.
6. **Talk and hardware.** Show the board, the LED grid and the nodes, and walk through how it works. Offer the judge a return visit once it's back.

**What sends us down a rung:**
- SENSOR BLIND for more than a few seconds. Name the link on screen ("the east link is blind"), never "the room is empty".
- NO DATA. The page is up but the feed has stopped.
- The model isn't trained. Don't retrain in front of a judge; drop to the recording.

**Climbing back up:** the operator fixes the issue (troubleshooting.md, first failed check) while the speaker keeps talking. Only Alexander touches hardware.

**Before the first judge, have ready:** a recorded session file on the laptop and the video file on the laptop, both checked to play offline. Neither is copied over the hotspot during the demo.

## Q&A

Short answers, said by the owner. Longer versions are in [judge-faq.md](judge-faq.md).

| Question | Owner | Short answer |
|---|---|---|
| Isn't this just signal strength? | Izet | Yes, signal strength on many links at once. One link tells you little; the pattern across all of them, compared to the empty-room baseline, tells you where the change is. That idea comes from radio tomographic imaging (Wilson and Patwari, 2010), and we credit it |
| Why not channel state information? | Alexander | The UNO Q's Wi-Fi driver can't give it to us. We built on what this board really exposes, on purpose |
| What runs on the Pi? | Alexander | No model. It's the router and a radio node. Every learned decision is on the UNO Q |
| How accurate is it? | Izet | Read the PROOF.md row: number, method, how many sessions, held-out. If the row is `__`, say "we haven't measured it yet, and we won't guess" |
| How fast is it? | Izet | Time per decision and end-to-end latency from PROOF.md, or `__` |
| What did the camera do? | Izet | It labelled where the person was during setup so the model could learn. No image is ever saved. It's unplugged now |
| What about privacy? | Ivan | No camera at run time, no images saved, our own network only, nothing to the cloud. It can't tell who you are |
| Does it work through walls? | Alexander | It works behind a curtain. We have only tested this one room, so that's all we claim |
| What if the furniture moves? | Izet | A new object shows up as change since the baseline. A big layout change needs a new baseline and new training, and we say so |
| Two people? | Izet | Not measured. We trained and tested with one person in the square |
| Who would use this? | Alejandro | Anyone fixing a dead zone: it tells you where to move the router. And a room-aware check-in: a no-movement alert for someone living alone that a wave clears, with no camera in the room |
| What was hardest? | Alexander | Getting enough Bluetooth readings a second, and keeping the sensing link steady |
| What would you do next? | Alejandro | Test in more rooms, measure more people, and more nodes for a bigger space |

**Rules for Q&A:**
- Answer in one or two sentences, then stop. Let them ask the next one.
- "We haven't measured that" is a good answer. A guessed number is not.
- Use the team words from AGENTS.md: no-movement alert, works behind a curtain, room-aware, on the Dragonwing CPU. Never their banned opposites.
- If someone challenges a number, open PROOF.md and show the method.

## Rehearsals

| Rehearsal | Where | On what | Judge played by | Pass when |
|---|---|---|---|---|
| R1 | Anywhere | Simulation (`python -m sim.rehearse`, the page with the fake feed) | Any teammate | The speaker hits every beat in order in 90 seconds |
| R2 | Build space | Live radio, loose markers | Someone outside the team if possible | One unbroken live run; every Q&A owner has answered their three hardest questions out loud |
| R3 | Presentation room | Live radio, taped layout, freshly trained | A teammate, then a stranger | Two clean runs in a row, plus one practised drop to rung 2 and one to rung 4 |

After each rehearsal, write one line per miss in the log below: the beat, what happened, the fix, who owns it.

### Rehearsal log

| Rehearsal | Beat | What went wrong | Fix | Owner |
|---|---|---|---|---|
| | | | | |

## Between judges

1. Operator: follow "Finish the live demo" in the runbook. Health must be `ok` before the next judge.
2. Speaker: note any question we couldn't answer well and add it to the Q&A table.
3. Proof: check whether PROOF.md has gained a row; if it has, the speaker uses the new number from now on.
4. Everyone: stay out of the square.

## Packing list (Alexander)

- UNO Q, powered hub, its power supply
- Raspberry Pi 5 and its power supply
- the one Ethernet cable, plus a spare
- both ESP32-S3 beacons and their power
- node stands, all at the same height
- the setup webcam
- the metal tray
- tape and loose markers
- the demo laptop, charged, with its charger
- a power strip

## Still to settle

- [ ] Organiser schedule: judging format and slot length (`__`), filled into the timeline
- [ ] Setup time measured in the build space (`__`)
- [ ] The recorded session file chosen and tested offline
- [ ] The video exported and tested offline
- [ ] Speaker confirmed (default: Alejandro)
