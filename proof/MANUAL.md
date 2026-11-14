# Sourced board measurements

After scoring at the current commit, enter a power reading with:
`python -m proof.manual --mode idle --watts <measured-W> --source '<meter model and method>' --measured-at <ISO-time>`.
Repeat for teaching and radio_only. Never use example numbers as readings.

Alexander starts counters with `sudo board/egress.sh start`, runs the intended
measurement interval, then saves **stdout only** from `sudo board/egress.sh count`
to a local text file. Only after that command succeeds, run:
`python -m proof.manual --egress-output <file> --egress-source '<method and interval>' --measured-at <ISO-time>`.
The output is a strict integer; errors or stderr text are rejected. Measured zero
is valid, a missing capture is not zero. The script does not start/reset counters.

No measurement is accepted without its source. Values from another commit or
power readings with a different meter source are refused. Existing proof fields
and their date remain intact. Each manual reading's actual date and source are
also recorded in a local `proof.manual.jsonl` evidence log; no device identifiers
or meter serial numbers belong in committed files. No hardware is needed by tests.
