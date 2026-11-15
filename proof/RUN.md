# One-command proof run

Run `sh proof/run_all.sh data/sessions --on-board`. Use `--dry-run` to inspect
commands and missing inputs without changing measurements. The runner classifies
files by meta purpose, separates train/object from heldout, runs scoring, timing,
false-event analysis and table rendering, then prints `missing:` lines and exits
2 if evidence remains incomplete. A missing input is never replaced by a number.

The section 6 baseline is `data/sessions/baseline.json`. For each heldout
`name.jsonl`, supply `name.states.jsonl` with the attribution described in
LATENCY.md. Declare negative empty/still session ids in the folder's
`proof-plan.json` as `{"negative_sessions":["session-id"]}` and provide matching
`name.events.jsonl` captured on the board clock. Multiple timing captures are
combined before calculating percentiles; negative-event counts and observed
minutes are summed before calculating rates. No stage overwrites a combined
measurement with only the last session. See FALSE_ALARMS.md for valid observations.
Negative recordings must be heldout sessions captured after a model exists.
An empty events/state capture is listed as missing, even if the file exists.
The final checklist includes all three power modes, images stored and model
inventory; those remain missing until actually measured.

Power and egress remain missing until measured separately. Requires the scoring,
latency and false-event modules to be present on main; missing dependencies stop
the run. The command never trains on heldout sessions and never enables simulated
proof. Alexander must record the live sessions and board timing evidence first.

The zone score's classes are empty plus each zone in the layout: three on the desk
layout (empty, Left, Right), so chance is 1 in 3; five on the square, so 1 in 5.
`proof.score` writes the confusion of camera zone against radio zone, with that
chance level, to `proof.confusion.json` next to `proof.json` (section 7 has no
field for it) and prints it. Quote the chance level next to the zone number. The
threshold baseline uses only links whose midpoint lies in a zone; on the desk that
is the four beacon links in front of the desk.
