# Recorded line evidence

This is the per-line table requested in #789. It describes measured RSSI, not classifier
accuracy. Use the actual layout and keep its placement unchanged during a recording.
Nothing here copies the hand-calculated numbers from the issue into measured proof.

1. On the board, note `git rev-parse HEAD`. Record numeric bus messages normally, with
   `src: live` and `recv_t`. Keep an independent operator log of when the spot is empty,
   someone stands still, someone moves, and a thing remains in the line with nobody there.
   Record several rounds. Leave transition seconds unlabelled. Do not use the brain's
   own predictions as the truth. No images or frames are needed or saved.
2. Beside `run.jsonl`, create `run.line-intervals.json` with the session id, SHA256 of
   the finished JSONL file, the full **board commit used when recording**, `truth: operator`,
   and confirmed intervals in seconds after that recording's meta `recv_t`:

   ```json
   {
     "session": "run",
     "recording_sha256": "REPLACE_WITH_SHA256_OF_FINISHED_RECORDING",
     "commit": "REPLACE_WITH_FULL_RECORDED_BOARD_COMMIT",
     "truth": "operator",
     "intervals": []
   }
   ```

   Each interval has `start_s`, `end_s`, and `kind` (`empty`, `still`, `moving`, or
   `object`). Fill only times actually logged; an empty list is rejected. Intervals must
   be ordered, disjoint and within the recorded time. Use `python -c "from proof.line_stats
   import digest; print(digest('data/sessions/run.jsonl'))"` on one line for the hash.
3. Run the normal pipeline:
   `python -m proof.run_all data/sessions --output proof/proof.json --document PROOF.md`.
   It discovers these annotations and writes the local companion `proof/proof.lines.json`,
   then renders the per-line table inside the normal generated PROOF.md block. Missing
   unrelated measurements can still give exit status 2; they stay `__`.
   Files with this companion go exclusively to the line scorer. Keep classifier training
   and held-out accuracy recordings separate; line labels are not camera accuracy labels.
4. To examine only these recordings before the rest of the proof is ready:
   `python -m proof.line_stats --pair data/sessions/run.jsonl data/sessions/run.line-intervals.json --output proof/proof.lines.json`,
   then `python -m proof.render_table --lines proof/proof.lines.json --output PROOF.md`.
   Repeat `--pair` for more sessions. By default each session gets separate rows.
   For separate empty/person/object files from one unchanged setup, add the same `group`
   name and `layout_sha256` to every interval file. Hash the actual active layout used on
   the board (including local placement overrides), and declare a group only while the
   physical placement stays unchanged. The tool then pools those windows to obtain a common
   empty reference. When the board's layout
   file was not kept, give `layout_note` instead of `layout_sha256`: the placement in the operator's
   own words (20 characters or more), the same on every file of the group; it is printed under the table.
   Different commits/layout hashes, duplicate files and overlapping capture
   times are refused. Every source hash remains in the table; unlabelled time between files
   is never exposure. The wire-format proof.json is unchanged.

The table uses non-overlapping one-second windows wholly inside each confirmed interval.
This is an explicitly defined method, not a reproduction of #95's hand calculation from
10-second block medians and adjacent empty blocks; those numbers need not be identical.
A usable window needs at least two distinct receive times and no gap greater than 0.6 s,
including its edges. Missing windows are excluded and the valid counts are printed.

- Quiet level: median of the empty windows' median RSSI.
- Person drop: smallest to largest quiet-minus-person window median, across still and moving.
- Separation: weakest empty median RSSI minus strongest person median RSSI. Positive means
  every observed person window was weaker than every empty window; negative means overlap.
- Largest empty dip: quiet level minus weakest empty median, bounded below by zero.
- Readings/second: raw readings in the labelled intervals divided by all their seconds,
  including sensor gaps. This is arrival rate, not a claim of continuous coverage.
- Jitter: median population standard deviation within one-second windows, separately for
  still, moving and object. A change between two steady windows is not within-window jitter.

Unavailable conditions stay `__`. Every report identifies the recording and annotation
hashes, the recorded board commit and the last recorded time. Mixed/synthetic sources,
clock reversals, stale hashes and invalid intervals are rejected before replacing output.
