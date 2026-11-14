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
```

- Reads bus messages on UDP 127.0.0.1:5601.
- Sends section 5 `state` about 10 times a second, and `event` messages as they happen, on `ws://<host>:8765/ws` (127.0.0.1 and 192.168.77.2).
- Takes `cmd` messages from the screen and passes each one on to the bus (127.0.0.1:5600) so it gets recorded.

| cmd | What the brain does |
|---|---|
| `baseline` | Sets label mode off and captures 20 s; a person in frame restarts it. Then `baseline_done`. |
| `record_start`, `record_stop` | Sends a `recording` event. The bus records. The brain keeps its own copy of the session from the bus's `meta` message until `record_stop`. |
| `train` | Trains on the kept sessions with purpose `train` or `object`, off the loop. Then `trained`. |
| `relearn` | Drops the model and trains again. |
| `label_mode` | Writes the mode to `--mode-file` (or `TEACHER_MODE_FILE`), which the camera teacher reads. |
| `router_moved`, `router_home` | Sets `router`; `pred` is null while it is off S-home. |
| `reset_alert` | Restarts the still timer. |
| `reset` | Between judges: clears the still timer and narration. Then `reset`. |
| `truth` | Kept for the crowd game. |

`brain/core.py` holds the rules with no sockets, so tests drive it with a fake clock.
Sent empty until their own issues land: `health` (always ok), `xray`, `objects`, `alert`, `checkin`, `advice`.
