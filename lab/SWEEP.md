# The settings sweep

One command tries a few thousand brain settings on our recordings and says which to use. It runs on rented CPUs (Modal), so it takes minutes, not an hour. It never touches the board: the board still trains its own model, and the board re-scores the chosen settings for PROOF.md.

## The command

```
modal run lab/sweep.py --sessions <folder> --scrubbed
```

- `<folder>` holds the bus's `<session>.jsonl` files plus the board's `baseline.json` (and `baselines.jsonl` if it exists). Put the layout's `nodes.json` there too if it isn't the one in `radio/`.
- `--scrubbed` says you ran `python -m sim.scrub <file> <clean copy>` on every file. The sweep refuses any file that still holds an address or a device name. It can't tell a scrubbed file from a clean unscrubbed one (the tool leaves no mark), so real recordings also need the flag.
- `--quick` runs a small grid, to check things work.
- To try it on simulated sessions: `python -m lab.sweep_sim sweep-sim --nodes radio/nodes.json`, then `modal run lab/sweep.py --sessions sweep-sim`.

## What it tries

Window length, features (absolute, or relative to the baseline as in PR #469), forest size (never above today's 60 trees at depth 12), link subsets (all, strip-crossing, four nodes, router plus one receiver), how many seconds of each walk it learns from (10 to 60 s), the smoothing and still-timer constants in `brain/alert.py`, and a "not sure" threshold. Each try runs the brain's own code.

## How it stays honest

- Only `train` and `object` recordings are used to pick settings. Each person is tested on a model that never saw them (and each desk, when there are two).
- `heldout` recordings are sealed: their hash goes in `sweep-out/sealed.json`, and a recording with those readings is refused for tuning even if it is renamed. They are scored once, at the end, for the chosen settings beside today's. A held-out recording that was already scored is never scored again: record a new one.
- Intervals are a bootstrap over sessions, not over decisions.
- With fewer than 4 training sessions, or 1 walker, it picks nothing and says what to record.

## What comes back

`sweep-out/<time>/`: `summary.md` (one paragraph: use these, how much better, record this next), `settings.json` (a proposal for a PR to the brain's constants), `top.md` (the top settings, the lesson-length table and the held-out score), `links.md` and `links.json` (what each set of links buys, in the shape of PR #487's device table) and `variants.jsonl` (every try). Everything says "simulated" or "from recordings". Nothing here goes into PROOF.md.

## Tests

```
python -m pytest lab
```
