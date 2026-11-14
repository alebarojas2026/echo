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

Power and egress remain missing until measured separately. Requires the scoring,
latency and false-event modules to be present on main; missing dependencies stop
the run. The command never trains on heldout sessions and never enables simulated
proof. Alexander must record the live sessions and board timing evidence first.
