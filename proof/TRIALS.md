# Crowd, tamper and lesson evidence

No real results are supplied here. Unknown values stay null / `__`. Synthetic
recordings exercise tests only. Publishing requires the UNO Q, live sources,
the approved section 7 schema (#556), and the same commit as existing proof.

1. Crowd (at least 3 minutes, plus confirmations): on the board run
   `python -m proof.trials_walk crowd-w1 crowd w1`. Start empty, then one person
   stands still in the configured alert zone while another makes 20 confirmed
   outside-only passes. Press Enter at the actual action, never ahead of it.
   Ctrl-C discards an unconfirmed interval and stops/disarms the recording.
2. Tamper (at least 140 seconds, plus confirmations): run
   `python -m proof.trials_walk tamper-w1 tamper w1`. Unplug the named configured
   beacon five times, leave it off six seconds, then restore it. The guide
   excludes ten seconds of recovery per trial and observes clean armed time.
3. Lesson (allow about 1 minute per attempt, longer if not ready): run
   `python -m proof.lesson lesson-w1 w1 --url ws://127.0.0.1:8765/ws --capture data/sessions/lesson-w1.states.jsonl`.
   Step as prompted. Observe learning, unplug the camera, then Ctrl-C. Do not
   reset, retrain or move the layout/model. Run
   `python -m proof.trials_walk after-w1 walk w1` (six seconds per configured
   zone, plus confirmations). Confirm each known centre with the camera off.

The bus saves each session; the guides save numeric `.states.jsonl` and
operator-confirmed `.trials.jsonl` sidecars on the same board clock. No images.
Run `python -m proof.trials --record <session.jsonl> <states.jsonl> <trials.jsonl>`
(repeat --record; use `-` instead of trials for lessons) to preview. Add
`--proof proof/proof.json` only on the board after #556 lands. `proof.run_all`
discovers these sidecars and renders PROOF.md through the usual pipeline.
Marked tamper trials and post-lesson walks go only to their specialized reports;
they do not join the unseen-walker zone score, even when their walker also trained.

Pass trials require continuous healthy armed capture. Report affected passes
n/N with Wilson 95% intervals, and distinct intrusion events/hour over observed
crowd time; the initial genuine entry is excluded. A still trial requires the
configured threshold plus five seconds. Tamper uses matching node IDs within
five seconds, including explicit blind states; gaps are unknown, never zero.
False tamper exposure excludes entire unplug/recovery intervals. Event IDs are
deduplicated. Repeated passes are trials, not independent people or identities.

On a layout with a presence line there is no model and no lesson: confirmed positions are scored
from the brain's own decisions with no trained model (no camera running), and no lesson is timed.

Lesson time begins at bus session start; this lesson must have fitted a model
and report 8/10 on its rolling telemetry, with continuous capture from the start
(first state within one second). Unreached convergence stays null per
lesson; min/max/median use only reached lessons. Post-unplug agreement compares
operator-confirmed positions with captured radio states sampled once per
200 ms, with a trained model, no heldout ID in its training provenance, and
continuous camera-off/healthy coverage. It is neither camera truth
after unplug nor a newly trained replay model. Keep train and heldout IDs unique.
Walk intervals bootstrap whole sessions, preserving correlated states; fewer
than two heldout walks leave the interval unknown.
