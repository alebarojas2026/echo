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
pip install -r sim/requirements.txt
python -m pytest brain
```
