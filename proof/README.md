# Held-out scoring

Run on the board after `brain.train.Model` and `brain.core.Brain` are available:

```sh
python -m proof.score --train data/sessions/train-*.jsonl \
  --heldout data/sessions/heldout-*.jsonl --baseline <capture-summary.json> \
  --on-board --output proof.json
```

The baseline summary must contain `base_dbm` and `expected_hz` dictionaries from
the valid 20 s empty-room capture. Do not estimate these from held-out sessions.
Declare held-out session purpose before capture. Each JSONL has exactly one v2
meta record and bus-stamped `recv_t` on every message. Duplicate sessions,
train/test overlap, wrong purposes and synthetic data are rejected.

Training uses only the explicitly supplied training/object files. Each held-out
session gets a fresh brain state machine and the trained model; radio and camera
health messages are replayed, while camera labels remain outside inference.
Only safe recorded router/alert commands are replayed; test data cannot retrain
the model. Scores join each decision to the majority camera label in its 1 s
`recv_t` window. Clipped, unlabeled and blind decisions are omitted, never scored
as an empty room. Compare coverage (usable decisions) as well as agreement.

The simple threshold baseline picks the link with the greatest drop at >=3 dB
and uses its geometric midpoint's zone; below threshold it predicts empty. The
threshold and mapping are fixed before evaluation. Person/object agreement uses
person labels and object-mode windows with no people plus >=2 s stable radio
drop >=3 dB and std <0.8 dB. Physical tray placement counts remain null.

False alarms means **false presence episodes during labeled-empty observation**,
not no-movement alerts. Count transitions to person and divide by nonoverlapping
empty observation time at the 0.1 s decision cadence; blind/unlabeled time is
excluded. The 95% interval resamples whole sessions (2,000 deterministic bootstrap
draws), keeping overlapping windows together. It is null with fewer than two
usable sessions; small session counts give weak evidence even with many windows.

Timings are measured around the real brain decision step. They and training time
stay null unless `--on-board` is passed on a Linux device identifying as UNO Q or
QRB2210. Power, network bytes, image storage and installed model counts stay null
until separately measured. Never populate them from assumptions or examples.

Self-tests: `python -m pytest proof/tests`. A real-brain integration test runs when
the brain package is installed; pure fixtures always run without it. `--allow-sim`
is for pipeline checks only and requires an output name other than `proof.json`.
Do not use synthetic output in the pitch or publish it as measured board proof.
