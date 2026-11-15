# Soak and chaos test: results (dev only)

Issue #168. Harness in `lab/soak/` (#205 and this PR). Simulated feed on a Windows PC, not the board. These numbers say how the software holds up over hours and under faults, not how fast the UNO Q is. None of them is a proof number and none goes on the screen.

## Verdict

Stable. In 2.5 hours with a fault about every 2 minutes, nothing crashed, no log has a traceback, memory and handles stayed flat outside recordings, the state rate held at 9.7 a second from the first half hour to the last, and the screen came back from every brain kill on its own, without a reload. On the "still" and "empty" paths there were no false check-ins, no false alerts and no unexplained SENSOR BLIND.

It found three defects, all fixed on main while the run was going:
1. #270 (fixed by #275): a brain crash or redeploy lost the trained model. The screen was live again within 5 s, but `pred` stayed null until the training paths were walked again (3.5 minutes with the sim).
2. #271 (fixed by #275): every recording stayed in the brain's memory, about 7 MB per recorded minute, never freed.
3. #272 (fixed by #315): a bus restart silently ended the open recording, and nothing told the brain or the screen.

Rechecked on newer main after the fixes (next section): all three hold. The rechecks found one more risk, #518 (brain) with #519 (runbook): the automatic baseline after `router_home` can run with the camera unplugged and someone in the square.

## Rechecks on newer main

Two shorter runs with the same harness, faults every minute (bus and brain kills first, then the rest), a 10-12 minute recording:

| | main `3c90db6`, 36 min | main `a49e060`, 20 min |
|---|---|---|
| Contract errors | 0 of 21,144 messages | 0 of 11,628 |
| Brain kill: `pred` back with no new walk | 3.0 s after the restart, for the kill before any router move (1) | 2.6 s, both kills, one right after a router move |
| Brain RSS through the recording | 128-131 MB | 128-140 MB |
| Bus kill during the recording | the file goes on after a 3.1 s hole; the bus logs "the bus restarted while recording demo-long: appending to it again" | the same |
| Screen after a brain kill | live again 4.9-5.1 s after the restart, no reload | 4.8-5.0 s |

(1) On `3c90db6` the two kills that came after a router move lost the model again: the automatic recalibration after `router_home` wrote a new baseline.json, and at the next start model.pkl's base no longer matched, so `pred` stayed null for 250-265 s, until the harness retrained. #344 (the place rule from #340) keeps the model through an automatic recalibration, and on `a49e060` it held.

Also from the rechecks:
- #518 and #519: on `3c90db6` a recalibration ran while the sim person walked through the square for about 14 of its 20 s, camera off. In the demo the camera is unplugged by then, and Alexander stands by the Pi when the 1 dB check runs.
- `router_home` with the tray still down or someone in the square fails the 1 dB check, and `pred` stays null ("Recalibrating") until a 20 s baseline completes: 27-32 s here, and over 60 s once, when no empty stretch came. That is the contract's rule (tray off first), but worth rehearsing.
- In the last 2 minutes of the `3c90db6` run another program on this PC drove the same default ports (its own sim feed and narrator, recordings `v1-empty`, `v1-lesson` and `v2-lesson`, and `train` commands); nothing after minute 33.9 is counted. During the `a49e060` run another copy of the soak proxy already held ports 5610 and 5611, so the faults went through that copy; the kill, recording and memory results don't depend on it. The 2.5 h run saw only 52 stray "live" readings from other programs' tests.

## What ran

- Code: main at `ae3cc8d` plus #113 at `c1c2474` (alert wiring, merged since) and #99 at `c702095` (HUD on the shared feed), merged locally and never pushed.
- Stack: `lab/soak/feeder.py` (the sim paths) -> `lab/soak/proxy.py` (faults) -> `python -m bus` -> `python -m brain.main` -> `python -m narrator.narrate` (no llama-server listening, so every sentence is the template) and `board/serve.py` serving `web/dist` to headless Chromium at `/?src=ws`, rendering on the CPU. The page was opened once and never reloaded.
- Paths, back to back at real speed: zone_tour, stand_still, metal_object, wave_checkin, dropped_link, camera_unplug, empty_room. Real speed because bus and brain stamp time with the wall clock; a faster sim would only change the link rates health judges by.
- Before the cycle and after every brain kill, the operator routine: baseline in the empty room, six training recordings, train. Plus one 8.5-minute `demo` recording.
- Faults, one about every 2 minutes, in turn: 8 packet bursts (90 s of 10% drops, 5% duplicates and up to 100 ms jitter; 6,775 dropped and 3,087 duplicated in all), 7 silent links (each link in turn, 10 s), 7 camera unplugs (30 s), 7 brain kills and 7 bus kills (hard kills, restarted after 3 s like the units' `Restart=always`), 7 router moves (S-W30 for 30 s, then home) and 7 resets.
- 86,864 states and 400 events, every one checked with `contracts/check.py`.

## Results

| What | Target | Measured |
|---|---|---|
| State rate | about 10/s | Median 9.7/s over 10 s windows (lowest 9.2); 9.70, 9.70, 9.68, 9.71, 9.69 in the five half hours. No gap over 1 s except the 7 brain kills. |
| State lag | | `t` to arrival 1 ms at the start and at the end, 66 ms at most. |
| Memory | flat | Bus 16 MB, narrator 21-30 MB, web server 16-23 MB, Chromium 570-620 MB, the page's JS heap 5.3-5.7 MB: all flat. Brain 151 -> 153 MB over each 15-minute life after training; +59 MB during the 8.5-minute recording, never given back (#271). |
| Handles | flat | Bus 105, narrator 154-160, web 143, Chromium 1,950-2,030. Brain +540 to +580 an hour in every life (Windows, from scikit-learn; see the notes). |
| Exceptions | none | 0 tracebacks in all 7 logs. The narrator logs only "model unreachable", then uses the template, as it should with no llama-server. |
| Brain kill (7) | back without a reload | States again 1.8-1.9 s after the restart. The screen showed NO DATA and went live again 4.6-5.0 s after the restart, never reloaded (the page retries every 0.5-5 s). The narrator reconnected every time. `pred` came back 204-228 s after it, and only after a new baseline, six recordings and train (#270). |
| Bus kill (7) | | Links healthy 0.9-1.0 s after the restart (4.0 s once, during dropped_link). A 3 s bus outage never reached SENSOR BLIND. The open recording wasn't picked up again (#272). |
| Silent link, 10 s (7) | SENSOR BLIND, then clear | Blind 4.2-4.4 s after the link went quiet; clear 3.8-4.0 s after it came back. |
| Camera off, 30 s (7) | | `cam` "off" and `teacher` null within 0.2 s; "on" again within 1 s. |
| Router move (7) | | `pred` null within 0.1 s of router_moved, back within 0.1 s of router_home (this code had no 1 dB check yet, #37). |
| Reset (7) | | Alert, check-in and narration cleared in the next state. Once the alert went back to counting 2.7 s later, because the person was still standing still. |
| Packet bursts (8) | no false alarms | No SENSOR BLIND and no unexpected check-in, alert or object during them. |
| SENSOR BLIND | no flaps | 44 episodes, each explained: 31 on the dropped_link path (the east beacon is silent for 10 s by design), 7 silent-link faults, 6 on dropped_link while another fault ran. None under 5 s, none unexplained. |
| NO DATA on screen | only when the feed stops | 8 episodes: page load and the 7 brain kills. None otherwise. |
| False check-ins / alerts | none | 0 on every path that doesn't expect one: 0 in 0.21 h of "still" (stand_still) and 0 in 0.62 h of "empty" (empty_room, metal_object). Table below. |
| Contract | no errors | 87,264 messages checked. Every error belongs to an issue already open at the time (next section). The 49 session files (181,733 lines) have no bad line. |
| Session files | | Training recordings 0.32-0.51 MB each. The 8.5-minute `demo` recording 7.75 MB, about 55 MB an hour. Bus log 1.97 MB in 2.5 h, mostly "lost" lines from the jitter. |

Check-ins, alerts and objects per path (training excluded):

| Path | Hours | Plays | Check-ins | Alerts | Objects |
|---|---|---|---|---|---|
| zone_tour | 0.34 | 38 | 0 | 0 | 0 |
| stand_still | 0.21 | 38 | 0 | 34, expected (1) | 0 |
| metal_object | 0.31 | 37 | 0 | 0 | 36, expected (2) |
| wave_checkin | 0.26 | 37 | 35, expected (3) | 6, expected | 0 |
| dropped_link | 0.31 | 37 | 0 | 0 | 0 |
| camera_unplug | 0.33 | 37 | 0 | 0 | 0 |
| empty_room | 0.31 | 37 | 0 | 0 | 0 |

(1) The 4 plays without an alert: 3 while the router-move fault held `pred` null (the timer pauses, as section 6 says) and the last one, cut short by the end of the run. (2) The one miss: the previous object hadn't cleared yet (#235). (3) The 2 misses were during brain kills. wave_checkin raises its own alert when the stand_still before it had none (missed, reset, or played during retraining).

## Seen again, already tracked

- #171 and #186: `pred.zone` and `pred.motion` null when nobody is there (23,894 states), and `links[].dbm` and `drop_db` null once a link has been quiet for 1 s (7,922 states).
- #172 item 1: event `info` keys event.json doesn't allow: `links` (baseline_done, blind_on, blind_off), `reason` (blind_on), `ver` and `train_s` (trained), `xy_m` and `drop_db` (object_on, object_off), `spot` (router_moved). 178 events.
- #173: `objects[].near` null. 880 states.
- #235: an object can outlast the empty_room after it (a ghost), once for a whole cycle.
- #38: no `cam_off` / `cam_on` events, so the narrator never says the camera went. `state.cam` itself follows the camera within 1 s.

## Not defects, but worth knowing

- **CPU starvation looks like a radio failure.** An earlier try (run1, stopped after 10 minutes) ran the stack at normal priority while the PC's other work held the CPU at 100% for long stretches. The brain stalled for 1 to 2.3 s at a time: the screen flashed NO DATA four times in 10 minutes (0.6-1.3 s each), and once all six links went SENSOR BLIND for 10 s although the feed was fine. At above-normal priority it never happened. On the board the brain shares 4 cores with llama-server and the camera teacher: give the brain unit a higher CPU priority than llama-server (`Nice=-5` or `CPUWeight=`) and look for this in the load bench (#130).
- **A new sim.send per path leaves the links stale for 3 to 5 s** on a busy machine while Python starts (run0). SENSOR BLIND at every path change was right for a feed that stops, but it's a rig artifact; `lab/soak/feeder.py` plays every path from one process instead. Anyone looping paths by hand with `sim.send` will see the same.
- **The bus counts reordered datagrams as lost.** With 100 ms jitter it logged about 30 times more "lost" than the proxy dropped (an older seq counts as a restart, then the gap counts again). Harmless on loopback and the Ethernet cable, which don't reorder.
- **Brain handles on Windows.** A trained brain's Windows handle count rises 540-580 an hour (an untrained one stays flat). It comes from scikit-learn's forest `predict_proba` (joblib), not brain code: one tree's `predict_proba` in a loop stays flat, the forest's grows. In a separate 25-minute run it went from 346 to about 590 and then held for the last 5 minutes, so it may level off. Linux is untested; on the board, `ls /proc/$(pgrep -f brain.main)/fd | wc -l` a few times over an hour settles it.

## Test rig limits

- A Windows 11 PC (16 threads, Python 3.12), shared with other work (median system CPU 76%), not the UNO Q (Linux on 4 Cortex-A53 cores). Memory and handle trends carry over; timings don't.
- The sim feed is regular and the model learns it easily, so the alarm numbers test the rules, timers and health logic, not radio accuracy. No real Wi-Fi or BLE timing, no llama-server (template narration only), no LED grid.
- The stack ran at above-normal priority (the browser at normal), so the PC's other load couldn't starve it; see the first note.
- Two earlier tries were thrown away for rig problems: run0 (a sim.send per path) and run1 (normal priority). No table number comes from them.
- One fault at a time. The rig itself paused the feed 8 times, up to 1.22 s, each at a `train` command; `proxy.jsonl` logs them.

## Reproduce

```
cd lab/soak && npm install && cd ../..
python lab/soak/soak.py --hours 2.5 --chaos-every 120 --out lab/soak/runs/r1
python lab/soak/report.py lab/soak/runs/r1      # the numbers above, also written to report.json
python -m pytest lab/soak                        # the proxy's tests
```
Needs psutil, websockets and jsonschema, Node for the probe, and a Playwright Chromium. Ports: bus 5600, brain 5601 and 8765, web 8080, proxy 5610 and 5611. Run folders stay local (`lab/soak/runs/` is ignored).
