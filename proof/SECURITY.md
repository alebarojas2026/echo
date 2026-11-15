# Evidence for presence and intrusion detection

All results come from predeclared heldout recordings. No real hardware result
exists yet. Missing evidence stays null in JSON and `__` in the proof table.
Synthetic sessions test this pipeline only; they never populate measured proof.

Alexander records on the board (its clock must stamp both streams):
`python -m proof.security_walk <new-id> entries <walker>` and, separately,
`python -m proof.security_walk <new-empty-id> empty <walker>`.
Use `python -m proof.security_walk <new-pass-id> passes <walker>` for brief
walk-throughs without stopping. Actual camera occupancy, not the prompt, decides
whether an entry lasted long enough to expect an intrusion.
These send the usual heldout record commands, arm the space, guide entries at
the named zone centres from nodes.json, and record at least 10 minutes empty.
Only numeric labels and state/event JSON are saved; no camera frames are saved.
The bus records `<id>.jsonl`; the coach captures `<id>.states.jsonl` on the same
board clock. Keep temporary ground-truth camera labels running for evaluation,
while predictions use radio alone. This is distinct from the camera-unplug demo.

Run `python -m proof.security --pair <session> <capture>` for a diagnostic.
Repeat `--pair` for more heldout sessions. Add `--train <separate-training-files>`
and `--baseline data/sessions/baseline.json` for the device comparison, then
`--proof proof/proof.json` on the board to publish measured data. The full runner
also runs this stage before rendering PROOF.md. The optional security format is
approved in #453; publishing stays gated until its schema lands with #415.

An entry is an independently labeled empty-to-present transition. Presence keeps
its two-second deadline. Intrusion allows `armed.hold_s + 2` seconds from
radio/nodes.json (hold defaults to 3); detection.within_s reports that intrusion
deadline and hold_s records the policy. Full evaluation windows need continuous
truth and captured states; gaps
exclude a trial rather than inventing a miss. Explicit blind states count as
missed detection, not an empty room. Armed intrusion trials also require armed
coverage throughout the longer deadline and confirmed occupancy for at least the
hold. Shorter walk-throughs are not intrusion misses. Detection reports n/N and Wilson 95% intervals (repeated
entries should be spread over walkers and sessions, not treated as new people).

False alarms count distinct captured `enter` and `intrusion` events during
independently observed empty, healthy time. Armed and all-empty denominators
are separate and reported in seconds alongside events/hour. No observed time
is unknown; a measured zero requires actual continuous capture. Event ids are
deduplicated within each session. Never interpret blind intervals as all clear.
An intrusion already matched to an eligible entry is never counted again as a
false alarm after the person leaves. `passed_by` never counts as an intrusion.
Its distinct event count and events/hour use all continuously captured armed
time, including explicit blind states, separately from the empty-only false-alarm
denominator. This is an observed event rate, not a count of people or recall.
The additional fields and revised deadline await schema #625; publication remains
schema-validated. Missing observed armed time stays null, rather than a zero rate.

Device rows come from nodes.json: all configured nodes; router, receiver and
the next two configured nodes; router plus receiver. Links require both endpoints.
Each row retrains the same zone-forest settings on masked training recordings;
only selected radio features reach inference. Presence is zone != 0. Missing
selected readings/baselines leave evidence unknown. This is recorded-data model
ablation, not a claim of a physical retest or reduced-device intrusion accuracy.
With four configured nodes, the first two rows intentionally match. Identical
recordings never appear in both training and heldout sets. No power, timing or
unmeasured hardware counts are inferred from replay. Use --allow-sim only without
--proof for development diagnostics.
