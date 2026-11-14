# Sourced board measurements

After scoring at the current commit, enter a power reading with:
`python -m proof.manual --mode idle --watts <measured-W> --duration-s <at-least-300> --source '<meter model and method>' --measured-at <ISO-time>`.
Repeat for teaching and radio_only. Never use example numbers as readings.

Alexander starts counters with `sudo board/egress.sh start`, runs the intended
measurement interval, then runs on the board:
`sudo python -m proof.manual --egress --egress-source '<method and interval>' --measured-at <ISO-time>`.
The command verifies the UNO Q identity and executes `board/egress.sh count`
itself; an arbitrary saved text file is not accepted. The output is a strict
integer; failed counter commands are rejected. Zero egress is valid, zero power
is not. The script does not start/reset counters.

Power requires at least 300 s per mode and a positive finite reading. Datasheet,
specification, rated, typical and URL sources are refused; use actual meter data.
No measurement is accepted without its source. Values from another commit or
power readings with a different meter source are refused. Existing proof fields
and their date remain intact. Each manual reading's actual date and source are
also recorded in a local `proof.manual.jsonl` evidence log; no device identifiers
or meter serial numbers belong in committed files. No hardware is needed by tests.
