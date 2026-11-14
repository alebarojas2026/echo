# Update the proof table

Preview `python -m proof.render_table --proof proof.json --document PROOF.md`.
To apply the result, add `--output PROOF.md`. Run only after recording real
measurements. The script changes known table rows and its marked generated
section; other prose and methods are preserved. Rerunning is idempotent.

Values, sample counts, timestamp and commit come from proof.json. Unmeasured
fields show `__`, including unknown counts and provenance. A measured zero is
retained. Planned sample targets are replaced with actual counts or `__` so they
cannot be mistaken for completed trials. Synthetic reports, invalid numbers and
measured rows without date/commit are rejected.

Section 7 does not contain end-to-end latency, no-movement latency, independent
coverage improvement or presence-accuracy counts. Those rows remain `__`.
Decision p50/p95 are shown only when measured; their N remains `__` because the
contract does not include a timing sample count. Do not infer it from zone N.

Tests use in-memory Markdown and JSON only: `python -m pytest proof/tests`.
