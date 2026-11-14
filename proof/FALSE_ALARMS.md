# False-event rates

`python -m proof.false_alarms <session.jsonl> <events.jsonl>` reports false
check-ins, no-movement alerts and object detections per observed minute. Add
`--proof proof/proof.json` only for live recordings to update their summed rate.
This replaces the scorer's simpler false-presence diagnostic in the proof strip.

The independent labels must show an empty floor or a person standing still.
Clipped frames, movement, object mode, zone changes and gaps over 0.5 s are
excluded. Observation ends at the last processed label; silence adds no time.
Events need capture-side `recv_t` on the board clock and their section 5 ids.
Repeated event captures are deduplicated. A still-person no-movement alert is
expected only in zone 1 after 60 s or zone 4 after 10 s of continuous observed
stillness; an early or wrong-zone alert is false. Waves and intentional object
placements belong in separate positive tests, not these negative recordings.

No usable observation yields null; measured zero requires usable live sessions.
Simulated sessions exercise the analysis but are refused for proof updates.
