# brain

Features, on-board training and live predictions. Formats: CONTRACTS.md v2.

## Features (`brain/features.py`)

- Windows are 1.0 s long with a 0.1 s hop, timed on `recv_t` (section 6).
- Per link: `n`, `mean`, `std`, `min`, `max` (dBm) and `drop_db` = baseline minus mean.
- The baseline is the per-link median over the 20 s baseline capture: `baseline(messages)`.
- A window's label is the majority of its non-clipped camera labels. A window with a clipped label or no label gets `label: None` and is left out of training.
- `vector(window)` gives a flat list for the model, in `feature_names()` order. A link with no readings counts as sitting on its baseline; link health reports it as missing.

Batch: `windows(messages, base)`. Live: `Windower(base).push(msg)` returns the windows that just closed.

## Tests

```
pip install -r brain/requirements.txt
python -m pytest brain
```

## The layout comes from radio/nodes.json (`brain/layout.py`)

Nothing in the brain names a node, a link or a zone of its own, except the two links section 6 names (`pi5>unoq:wifi` for the check-in and the advice).
- Links, in file order, are the feature vector's order, the rows of `state.links` and the x-ray's rows.
- Zones give `probs` its length and the alert its limits.
- The x-ray grid: with `frame.strip_m` (the desk layout) cells of 0.125 m over `frame.size_m` plus 0.2 m each side (16 x 12 for 1.6 x 1.1 m); without it the square's 10 x 10. The zone of a point follows the same switch (`1 + (x >= zone_split_x_m)` inside the strip and 0 off it, or the square's four). `sim/layout.py` does the same.
- The router is the node with the `router` role. "A pi5 link" (the 3 s check after `router_home`) is a link with that node as tx or rx, by the parsed ends: `pi5b` is another node.
- Links whose receiver has no cable (`pi5b`: its readings ride the sensing hotspot, which the demo blocks on purpose) are judged like any link and show stale or blind in their own rows, and health is then degraded; but they never make health blind, never appear in `health.blind`, never hide `pred` and never pause the alert.
- A model file remembers its feature names and zones, so one from another layout is refused at start with a line in the log.
- `RADIO_SIGHT_NODES=<file>` makes the brain read another layout file. The tests in brain/tests pin their own (the 2 x 2 m square, `brain/tests/square_nodes.json`, with their own copies of the sim paths), so they don't change when the room does; `brain/tests/test_layout.py` runs the loop on the desk layout and on whatever radio/nodes.json holds.

## Training (`brain/train.py`)

Three random forests share one feature vector per window:
- `zone`: class 0 (empty) and one class per zone in radio/nodes.json, so its probabilities are the contract's `probs` (`[empty, z1, ...]`: five entries on the square, three on the desk strip);
- `motion`: moving or still, trained on windows with someone present;
- `kind`: person, object or none.

`Model(base).fit(sessions)` trains on 4 cores. `predict(window)` returns the contract's `pred` block, and `info()` returns the `model` block. A session is `{"meta": <meta message>, "messages": [...]}`.

`leave_one_person_out(sessions, base)` scores zone accuracy with each walker tested on a model that never saw them. Sessions without a walker (empty room, objects) always stay in training.

Install: `pip install -r brain/requirements.txt` (scikit-learn, since onnxruntime crashes on the board).

## Live loop (`brain/main.py`, `brain/core.py`)

```
python -m brain.main                 # on the board
python -m brain.main --feed-clock    # with a recorded file played faster than real time
python -m brain.main --nodes radio/nodes.json   # nodes, links and zones (this is the default)
python -m brain.main --bus 127.0.0.1:5600      # where commands are passed on to the bus (or BRAIN_BUS)
python -m brain.main --sessions data/sessions  # where baseline.json is written and read back at start
```

- Reads bus messages on UDP 127.0.0.1:5601.
- Sends section 5 `state` about 10 times a second, and `event` messages as they happen, on `ws://<host>:8765/ws` (127.0.0.1 and 192.168.77.2).
- If 192.168.77.2 isn't on the machine yet (the board's Ethernet comes up after the brain starts), it listens on 127.0.0.1 and retries the other address every 2 s until it binds. No restart needed. On a laptop it just keeps retrying quietly.
- Takes `cmd` messages from the screen and passes each one on to the bus (127.0.0.1:5600) so it gets recorded.

| cmd | What the brain does |
|---|---|
| `baseline` | Sets label mode off and captures 20 s. With the camera off there is nobody to ask and the operator keeps the area empty; with it on, it must see nobody. The 20 s start again whenever a section 6 condition breaks: the camera is on and its labels stop or it sees anybody, label mode is turned on, health is not ok, or a link goes quiet for 1 s. If it still can't start 120 s after the command (with or without `keep_model`), it is given up (logged; the old baseline and the model stay, `pred` comes back), so a Baseline pressed by mistake during a demo doesn't hide `pred` for good. Then it writes `data/sessions/baseline.json` and sends `baseline_done`. `baseline {keep_model: true}` is the same layout set down again (another desk, a knocked beacon): only the baseline is new, the model and the recordings stay, and each recording keeps the baseline it was made on (`data/sessions/baselines.jsonl`). The model's features are all drops and spreads against the baseline, never levels in dBm, which is why it carries over. Without `keep_model`: **A baseline asked for by hand means a new place**: when it finishes, the model is dropped (`pred` is null and `model.trained` false until the next `train`) and recordings made before it are never trained on again. Their files stay in `data/sessions`. The time is kept in `data/sessions/place.json`. |
| `record_start`, `record_stop` | Sends a `recording` event. The bus records. The brain keeps its own copy of the session from the bus's `meta` message until `record_stop`. |
| `train` | Trains on the kept sessions with purpose `train` or `object`, off the loop. Then `trained`. |
| `relearn` | Drops the model and trains again, from this place's recordings only. |
| `label_mode` | Writes the mode to `--mode-file` (or `TEACHER_MODE_FILE`), which the camera teacher reads. |
| `router_moved` | Sets `router`, moves the x-ray's geometry and freezes the advice's `before_dbm`. `pred` is null while the router is off S-home. 5 s later `after_dbm` is filled (the median over 3 s, starting 2 s after the move) and `advice_result` goes out. |
| `router_home` | Back on S-home: clears the advice and the x-ray, then checks for 3 s that every pi5 link sits within 1 dB of its base (`pred` stays null meanwhile). If one doesn't, it sends `recalibrating` and runs an automatic 20 s baseline; if that baseline moved a link by more than 1 dB it sends `drift`, which is the cue for `relearn`. |
| (tamper, no cmd) | While armed, a node is silent when none of the links it sends or receives on (from radio/nodes.json) has had a reading for 3 s. It raises `tamper` once with `info.node` and is listed in `state.tamper` until all its links have had readings for 2 s without a 3 s gap (`tamper_cleared`), or until disarm or `reset`. Arming with a node already silent raises it at once. It is judged whatever health says, so it works while the sensor is blind; 60% packet loss with 1 s bursts never reaches 3 s of silence. Not armed: nothing. `state.tamper` is sent only while a node is listed. |
| `reset_alert` | Clears the alert and restarts the still timer. |
| `reset` | Between judges: clears the alert, still timer, check-in and narration, and disarms. Then `reset`. |
| `arm` | `{on: true}` arms ("this space should be empty now"): `state.armed` is true and `armed` goes out. `{on: false}` (or `reset`) disarms and sends `disarmed`. While armed, one `intrusion` event with the zone each time a person appears: present with kind person in 6 of the last 10 decisions, after not being so. Arming with somebody already there raises it within 6 decisions. Objects never raise it, and nothing is raised from a decision that is hidden (blind, recalibrating, router away). `state.armed` is sent only while true until state.json has the field (#440). |
| `truth` | Kept for the crowd game. |

`brain/core.py` holds the rules with no sockets, so tests drive it with a fake clock.
Link health (`brain/health.py`), the x-ray and objects (`brain/xray.py`) and the check-in and alert (`brain/alert.py`) are fed from here: every reading goes to all three, and their output fills `links`, `health`, `xray`, `objects`, `alert` and `checkin`. `pred` is null while health is blind, and the LED grid then shows "?". **Restart and memory.** On `trained` the model is saved to `data/sessions/model.pkl` (written to a temp file, then renamed). At start the brain loads `baseline.json`, then `model.pkl` if it was fit in that same place (`place.json`), so after a crash or redeploy `pred` is back without a new walk; a model from another place, or a damaged file, is ignored. The automatic baseline after `router_home` keeps the place, so the model and the recordings survive it, also across a restart. Recordings are not kept in memory: when the bus.s `<session>.jsonl` is on disk the brain holds only its meta, and `train` reads the files back. `train` also picks up this place.s `train` and `object` recordings straight from the folder, so ones made before a restart (or cut in two by one) are still trained on. Other purposes (`demo`, `heldout`, `crowd`) are never held. The brain and the bus must point at the same `--sessions` folder for this; if the file isn't there, the recording stays in memory as before.

`advice` comes from `advisor.advise` while the router is on S-home. One object gets one advice: the first answer stays (same id, spot and text) until the advice goes away or is about an object more than 0.5 m from it, so a tie between two spots never flips the sentence; the brain adds `before_dbm` (the median of `pi5>unoq:wifi` over the last 3 s, kept current) and sends an `advice` event when a new one appears.

Events for the narrator, each with only the info keys `contracts/schemas/event.json` allows (zone, link, node, before_dbm, after_dbm, on, session) and no nulls:

| Events | Sent when | info |
|---|---|---|
| `enter`, `exit`, `zone_change` | the decision's zone has held for 5 decisions in a row (0.5 s), so one flickering decision says nothing | `zone` (for `exit`, the zone they left from) |
| `checkin`, `alert_on`, `alert_off` | from the check-in and alert rules | `zone`, and `link` on a check-in |
| `object_on`, `object_off` | from the x-ray | `zone`, `link`, `node` |
| `blind_on`, `blind_off` | from link health | `link` |
| `advice`, `advice_result`, `router_moved`, `router_home`, `recalibrating`, `drift` | the router and advice steps | `link`, `node`, `before_dbm`, `after_dbm` as they apply |
| `cam_on`, `cam_off`, `cam_stalled` | the camera's state changes, or it sends nothing for 3 s (off) | none |
| `trained`, `baseline_done`, `reset` | as named | none |
| `recording` | `record_start` and `record_stop` | `on`, `session` |

The automatic baseline after `router_home` also runs with the camera unplugged; with the camera on it must still see nobody. A baseline asked for with the `baseline` cmd always needs the camera.

## Check-in and no-movement alert (`brain/alert.py`)

`Watch` holds both section 6 rules. Give it every rssi message (`on_rssi`) and every decision (`on_pred`); it returns the state's `alert` block (`alert_block()`), the last `checkin`, and `alert_on`, `alert_off` and `checkin` events (`pop_events()`).

- **Check-in:** 4 alternating crossings of +/-1.5 dB around the 1 s rolling median on `pi5>unoq:wifi` within 2.5 s, with the zone unchanged, a person present and no other link changing by more than 3 dB. Readings are averaged 3 at a time first, so plain noise can't cross. One wave is one check-in.
- **Alert:** `still_s` counts while a person stays still in one zone. Decisions are smoothed first: the zone and kind are the majority of the last 10 decisions, and the timer resets only after 5 "moving" decisions in a row, so one blip doesn't restart a 10 s count. `check_on` at the zone's `still_alert_s` from `radio/nodes.json`; zones with null never alert, and objects never alert. Only a check-in or `reset_alert` clears it (`Watch.reset_alert()`); the `reset` cmd is `Watch.reset()`, which also forgets the last check-in. The timer pauses while `pred` is null.
- **LED grid:** `show_zone(n)` when the shown zone changes (`-1`, the "?", while `pred` is null or spans 2 or more zones), `alert(on)` when the alert turns on or off, `smile()` on a check-in. `led_grid()` gives the Bridge version on the board and a stand-in elsewhere.

The constants at the top of the file are what gate 8 tunes.

## The live lesson (`brain/lesson.py`)

The camera teaches the radio on whoever is standing there, and is then unplugged. The screen sends commands that already exist:

1. `label_mode` person, then `record_start` with purpose `train`: the person steps left and right for about 20 s.
2. `train`, with the recording still open. That fit reads the recording as far as it has got (plus this place's earlier recordings, so an empty-room recording made at setup still teaches "nobody"), and it starts the lesson.
3. While the camera is on, the brain fits again every 15 s from the growing recording.
4. When the camera goes off, or on `record_stop`, there is one last fit. The model carries on; nothing else changes.

During the lesson `model.training` stays set and carries `lesson: {started_t, agree, of, fits, fitting}`: of the last `of` (10 at most) decisions that had a fresh, non-clipped camera label, `agree` gave the camera's answer. That is the screen's "learning: 6 of 10". Wording for CONTRACTS.md is in #482.

A `train` with no recording open, or after `record_stop`, is the plain one-off fit it always was. `python -m proof.lesson <session> <walker>` runs a lesson from a terminal and times it.

## Recording steps for training

How the sessions are walked decides what the model can learn. These steps come from the simulation lab (#221, #224), not from measurements; the held-out score in PROOF.md is what counts. Redo all of it in the presentation room, after the baseline there.

**Before anything:** run a `baseline` with nobody in the camera's view.

**Person sessions** (`record_start` with purpose `train`, `label_mode` person), one per walker:
1. Stand still for about 10 s on each of the four marked spots, one per zone. Without long stands the model never learns "still", and the no-movement alert can't count.
2. Then walk freely around the square for about 30 s.
3. Record at least 3 different walkers, more if there's time. A walker used for the held-out score (purpose `heldout`) must not appear in any `train` session.

**Empty session** (purpose `train`, `label_mode` person): 30 s with nobody in the square.

**Object session** (purpose `object`, `label_mode` object), with nobody in the camera's view while the tray is down:
1. Put the tray exactly on the T1 mark for at least 15 s.
2. Move it about 5 cm to one side for at least 15 s, then about 5 cm to the other side for at least 15 s.
3. Step out of view each time before counting. Windows with anybody in frame, and the 2 s after, are left out of training.

In the demo, put the tray back on the same T1 mark. The model recognises it only near where it was recorded.
