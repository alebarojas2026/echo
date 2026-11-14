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

## Training (`brain/train.py`)

Three random forests share one feature vector per window:
- `zone`: classes 0-4 (0 = empty), so its probabilities are the contract's `probs`;
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
- Takes `cmd` messages from the screen and passes each one on to the bus (127.0.0.1:5600) so it gets recorded.

| cmd | What the brain does |
|---|---|
| `baseline` | Sets label mode off and captures 20 s. The 20 s start again whenever a section 6 condition breaks: the camera is off or its labels stop, it sees anybody, label mode is turned on, health is not ok, or a link goes quiet for 1 s. Then it writes `data/sessions/baseline.json` and sends `baseline_done`. |
| `record_start`, `record_stop` | Sends a `recording` event. The bus records. The brain keeps its own copy of the session from the bus's `meta` message until `record_stop`. |
| `train` | Trains on the kept sessions with purpose `train` or `object`, off the loop. Then `trained`. |
| `relearn` | Drops the model and trains again. |
| `label_mode` | Writes the mode to `--mode-file` (or `TEACHER_MODE_FILE`), which the camera teacher reads. |
| `router_moved` | Sets `router`, moves the x-ray's geometry and freezes the advice's `before_dbm`. `pred` is null while the router is off S-home. 5 s later `after_dbm` is filled (the median over 3 s, starting 2 s after the move) and `advice_result` goes out. |
| `router_home` | Back on S-home: clears the advice and the x-ray, then checks for 3 s that every pi5 link sits within 1 dB of its base (`pred` stays null meanwhile). If one doesn't, it sends `recalibrating` and runs an automatic 20 s baseline; if that baseline moved a link by more than 1 dB it sends `drift`, which is the cue for `relearn`. |
| `reset_alert` | Clears the alert and restarts the still timer. |
| `reset` | Between judges: clears the alert, still timer, check-in and narration. Then `reset`. |
| `truth` | Kept for the crowd game. |

`brain/core.py` holds the rules with no sockets, so tests drive it with a fake clock.
Link health (`brain/health.py`), the x-ray and objects (`brain/xray.py`) and the check-in and alert (`brain/alert.py`) are fed from here: every reading goes to all three, and their output fills `links`, `health`, `xray`, `objects`, `alert` and `checkin`. `pred` is null while health is blind, and the LED grid then shows "?". `advice` comes from `advisor.advise` while the router is on S-home; the brain adds `before_dbm` (the median of `pi5>unoq:wifi` over the last 3 s, kept current) and sends an `advice` event when a new one appears.

The automatic baseline after `router_home` also runs with the camera unplugged; with the camera on it must still see nobody. A baseline asked for with the `baseline` cmd always needs the camera.

## Check-in and no-movement alert (`brain/alert.py`)

`Watch` holds both section 6 rules. Give it every rssi message (`on_rssi`) and every decision (`on_pred`); it returns the state's `alert` block (`alert_block()`), the last `checkin`, and `alert_on`, `alert_off` and `checkin` events (`pop_events()`).

- **Check-in:** 4 alternating crossings of +/-1.5 dB around the 1 s rolling median on `pi5>unoq:wifi` within 2.5 s, with the zone unchanged, a person present and no other link changing by more than 3 dB. Readings are averaged 3 at a time first, so plain noise can't cross. One wave is one check-in.
- **Alert:** `still_s` counts while a person stays still in one zone. `check_on` at the zone's `still_alert_s` from `radio/nodes.json`; zones with null never alert, and objects never alert. Only a check-in or `reset_alert` clears it (`Watch.reset_alert()`); the `reset` cmd is `Watch.reset()`, which also forgets the last check-in. The timer pauses while `pred` is null.
- **LED grid:** `show_zone(n)` when the shown zone changes (`-1`, the "?", while `pred` is null or spans 2 or more zones), `alert(on)` when the alert turns on or off, `smile()` on a check-in. `led_grid()` gives the Bridge version on the board and a stand-in elsewhere.

The constants at the top of the file are what gate 8 tunes.
