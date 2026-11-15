# Recordings replayed through the brain

For one spot with a presence line, where the line alone decides and there is no model, no
lesson and no camera. It turns short recordings taken on the kit into PROOF.md rows without
anybody entering a number by hand:

- the readings are real: session files as the bus wrote them, every row `src: live`;
- the decisions are the brain's own: `brain.core.Brain` on the layout file, started cold on a
  baseline taken from the run's first empty recording, armed, with no model;
- the truth is the operator's index: what each recording was (empty, a person standing, still,
  moving), written down when it was recorded.

It is not a live run. Each recording is all-empty or all-person, and the seconds between them
were not recorded, so a run's recordings are joined end to end. Every row says "replayed through
the brain from recordings taken on the kit", and the step-on itself is in none of them.

## The plan

A JSON file kept beside the recordings, never in the repo:

```json
{"truth": "operator", "people": 1, "night": "the night it was recorded",
 "recorded_commit": "FULL_COMMIT_THE_BOARD_RAN",
 "runs": [{"id": "main", "placement": "in the open",
           "sessions": [{"session": "s1", "is": "baseline", "role": "tuning"},
                        {"session": "s2", "is": "person",   "role": "report"},
                        {"session": "s3", "is": "empty",    "role": "report"}]}]}
```

A run is one sitting with the devices left where they are. Its first session is the baseline,
or the run names `baseline_s` (that many seconds of its first session). `is` is one of
baseline, empty, person, still, moving, walk, side, behind, thing.

**The wall between tuning and reporting.** Every session is `tuning` or `report`, and that is
decided before any setting is chosen. Tuning sessions are played, because the brain has to live
through the sitting in order, and are never scored. A run with nothing to report is refused. A
kind that exists only as tuning (a walk-through recorded once) is listed under the table as
"seen once, used for tuning, not a result". Only empty, person, still and moving have a scorer.

A run with `"limit": "why"` is a placement declared beforehand as one that is expected to fail.
It gets its own row and is left out of the total; a plan made of limits alone is refused.

## Run it

```sh
python -m proof.replayed <folder> <plan.json> --layout radio/layouts/gate.json --output proof/proof.replay.json
python -m proof.render_table --replay proof/proof.replay.json --lines proof/proof.lines.json --output PROOF.md
```

The first prints the rows and writes the companion report; without `--output` it only previews.
The wire-format proof.json is unchanged. The brain's code and the layout files must be a clean
checkout: the report names the last commit that touched them, and the layout file's SHA256.

## How each row is scored

- **Stand found:** a person recording that follows an empty one. Found when the brain says
  somebody for 0.3 s in a row during it (the rule of proof.shuffled).
- **Time from the signal crossing to the decision:** from the first reading of that recording to
  the start of that stretch. It is the delay of the rule. The time a body takes to step in was
  not recorded and is not in it.
- **False presence:** every stretch in which the brain says somebody during an empty recording,
  however short. After a person's recording the brain is given up to 2 s to let go; anything
  after that counts. Empty time is the time with known decisions; hidden decisions are not clean
  empty time. Intrusions, passed-by and arrivals said during it are counted too.
- **Still / moving:** ten decisions a second from 3 s into the session, compared with what the
  session was. Decisions inside one session are not independent trials: one session shows it can
  work, not how often.

Counts carry an exact (Clopper-Pearson) 95% range in plain words, rounded outward; the rate
carries the exact (Poisson) upper end for the minutes observed. Quote the count and the range,
never a bare percentage.
