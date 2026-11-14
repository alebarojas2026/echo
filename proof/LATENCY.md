# Logged timing

`python -m proof.latency <bus-session.jsonl> <captured-states.jsonl>` reports
decision and input-to-first-state p50/p95. Add `--proof proof/proof.json` only
for live board captures. Simulated reports stay outside the proof file.

A plain section 5 state contains a rolling median decision time, not individual
samples, and contains no identity of the reading it reflects. Exact latency
cannot be recovered from those fields alone. Without capture evidence this
script reports null rather than guessing from signal values or producer `t`.

The capture instrument must wrap each unchanged state in a JSONL record with
`recv_t` (board capture time), `state` (the section 5 message), `input_recv_t`
(the bus-stamped reading actually used), and optional `decision_ms` (an
individually measured span). These are local instrumentation records, never
messages sent to the bus. Keep all clocks on the board. The first record for
each attributed reading is counted; repeated display states cannot add samples.
Synthetic spans may exercise tests but cannot populate measured proof.

End-to-end timing is printed separately because section 7 has no field for it.
Do not copy the state's rolling median into a per-decision p95. Board capture
instrumentation and real sessions are needed before these numbers are measured.
Measured updates require the UNO Q device identity. Missing individual spans
leave prior timings untouched. Existing evidence from another commit is refused;
rerun scoring at the current commit rather than relabeling old results.
