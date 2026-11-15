# Held-out presence measurement

Use a different real person from every training/lesson participant. Keep their
pseudonym stable; renaming a training walker is not a heldout experiment.
Keep the trained model and layout fixed, and physically unplug the camera.

On the board, run `python -m proof.presence_walk cycles-w2 w2`. Allow about
25 minutes: setup and ten cycles of at least 60 seconds completely empty,
then at least 60 seconds occupied. Confirm actual entry/exit when prompted;
never confirm a scheduled action that did not happen. The coach checks for a
fresh camera-off state and a trained model before starting the truth log.
Ctrl-C stops recording; an incomplete cycle is refused by the scorer.

The bus records `data/sessions/cycles-w2.jsonl`; the guide captures numeric
state/event JSON in `cycles-w2.states.jsonl` and independently confirmed truth
in `cycles-w2.presence.csv`. No images or video. CSV header: `recv_t,present`;
board epoch milliseconds, 0 empty / 1 occupied, starting and ending empty.
Every phase needs at least 60 seconds. Missing decisions never mean empty.

Preview with `python -m proof.presence data/sessions/cycles-w2.jsonl
data/sessions/cycles-w2.states.jsonl data/sessions/cycles-w2.presence.csv
--train <all-original-training-files>`. Add `--proof proof/proof.json` only on
the board after schema #656 lands. `proof.run_all` discovers the CSV and keeps
these camera-off cycles separate from the camera-based zone score. Repeat
`--more-record SESSION STATES CSV` for additional independent recordings.

The scorer checks heldout purpose, source session IDs and walkers, complete
model training metadata, a fixed model version, and camera off throughout.
It scores one healthy known prediction per observed second against the log.
Blind/missing seconds are excluded; N is observed sampled seconds. The always-
empty baseline uses exactly those samples, so missing/lopsided coverage cannot
look better merely because most observed samples are empty.

The camera-based scorer also collapses 1 Hz confusion into presence; its cycle
count stays null. Zone confusion retains its original window resolution and
reports the majority-class baseline beside uniform chance. Pending served
fields stay in the diagnostic confusion sidecar until schema #656 supports
them. Synthetic diagnostics are labelled and cannot update measured proof.
