# False-event rates

`python -m proof.false_alarms <session.jsonl> <events.jsonl>` reports false
check-ins, no-movement alerts and object detections per observed minute. Add
`--proof proof/proof.json` only for live recordings to update their summed rate.
The zone scorer leaves this field null; this module is its only measurement source.

The independent labels must show an empty floor or a person standing still.
Clipped frames, movement, object mode, zone changes and gaps over 0.5 s are
excluded. Observation ends at the last processed label; silence adds no time.
Events need capture-side `recv_t` on the board clock and their section 5 ids.
Repeated event captures are deduplicated. A still-person no-movement alert is
expected only after the corresponding `still_alert_s` in `radio/nodes.json` of
continuous observed stillness; an early or wrong-zone alert is false. Waves and intentional object
placements belong in separate positive tests, not these negative recordings.

No usable observation yields null; measured zero requires usable live sessions.
Simulated sessions exercise the analysis but are refused for proof updates.
Existing measurements from a different commit are refused rather than restamped.
The capture must be nonempty and use the same board recv_t clock. A continuous
capture may begin before the session and finish after it; its coverage and event
counts are clipped to the session range before event-id deduplication. A capture
with no overlap is refused; touching a boundary alone provides no observation.
Include
captured state heartbeats to establish coverage when no events occur. Only the
intersection of capture coverage and valid labeled observation enters exposure.
An empty capture is missing evidence, not zero events. Measured writes require
the UNO Q identity just like timing updates.
