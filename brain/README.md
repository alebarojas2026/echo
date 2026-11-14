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

## Check-in and no-movement alert (`brain/alert.py`)

`Watch` holds both section 6 rules. Give it every rssi message (`on_rssi`) and every decision (`on_pred`); it returns the state's `alert` block (`alert_block()`), the last `checkin`, and `alert_on`, `alert_off` and `checkin` events (`pop_events()`).

- **Check-in:** 4 alternating crossings of +/-1.5 dB around the 1 s rolling median on `pi5>unoq:wifi` within 2.5 s, with the zone unchanged, a person present and no other link changing by more than 3 dB. Readings are averaged 3 at a time first, so plain noise can't cross. One wave is one check-in.
- **Alert:** `still_s` counts while a person stays still in one zone. `check_on` at the zone's `still_alert_s` from `radio/nodes.json`; zones with null never alert, and objects never alert. Only a check-in or `reset_alert` clears it. The timer pauses while `pred` is null.
- **LED grid:** `show_zone(n)` on a zone change, `alert(on)` when the alert turns on or off, `smile()` on a check-in. `led_grid()` gives the Bridge version on the board and a stand-in elsewhere.

The constants at the top of the file are what gate 8 tunes.
