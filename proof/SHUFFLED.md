# Shuffled trials and the empty hour

Presence numbers for one spot. Everything is scored from the brain's own states and
events as `proof.shuffled` hears them on the WebSocket; nothing is entered by hand.

Run from a laptop on the kit's network. If the board has an operator key, set
`OPERATOR_KEY` in the shell first (it arms and disarms the space).

1. **Tuning recording** (settings may be changed after looking at it):
   `python -m proof.shuffled trials <new-id> <walker> --tuning`, then
   `python -m proof.shuffled tune data/sessions/<id>.shuffled.jsonl`.
2. **Report recording**, later, with the settings left alone:
   `python -m proof.shuffled trials <new-id> <walker>`, then
   `python -m proof.shuffled report data/sessions/<id>.shuffled.jsonl`.
3. **Empty hour**, unattended: `python -m proof.shuffled empty <new-id> --minutes 60`,
   then `report` on its file.

A trial run is 40 trials of 20 s, each followed by 5 s to step away (about 17 minutes):
16 stand on the spot, 12 empty, 12 walk through without stopping, in an order drawn when
the run starts. The terminal says each cue, and speaks it where the laptop can.

How each is scored:
- **Stand:** detected when the brain says someone is present for 0.3 s in a row during
  the 20 s. The time is from the cue, so it includes the person stepping on.
- **Empty:** a false presence if any known state says someone is present during the 20 s. Even a brief blip counts. The 5 s after a
  trial are not scored.
- **Walk-through:** intrusion, passed-by or nothing, from the brain's events during the
  trial and the 5 s after it. The space is armed for the whole run.
- **Empty hour:** all false presence stretches (including brief blips), false intrusions, and per hour, over the length
  actually observed with known decisions. Gaps over 0.5 s and hidden predictions do not count as clean empty time.
- A trial with incomplete or unknown state coverage is left out and counted as left out.

The wall between tuning and reporting: a recording is made as one or the other and keeps
that role. `report` refuses a tuning recording, a recording that isn't live, and a file
without a role. `tune` refuses a report recording.

Results are said as counts with an exact (Clopper-Pearson) 95% range, in plain words:
"15 of 16 detected; with this few trials the true rate is probably between 69% and 100%".
Whole-percent endpoints round outward; 15/16 has exact bounds about 69.77% and 99.84%, so the upper endpoint must not be clipped to 99%. Quote the count and range, not a bare percentage.
