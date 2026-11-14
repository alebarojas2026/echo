# Can you hide from Wi-Fi?

A standalone tally page for the crowd game. It does not touch the main web shell.

## How a round works

1. A visitor steps into the square and tries to stay out of sight.
2. The operator taps the zone the visitor is really standing in (or presses 1 to 4).
3. The page compares that with the board's current guess from radio alone:
   - **Found**: the board has a person in that zone.
   - **Hid**: the board has them in another zone, sees an object, or sees nobody.
4. The tally updates, and the page sends the `truth` command (`{zone}`) to the brain.

A round is not counted when the feed is stale (NO DATA, last state older than 1 s) or the board has
no guess (`pred` is null: not trained yet, SENSOR BLIND, recalibrating, or the router is off home).
Rounds played on a `sim` or `replay` feed are practice and never reach the tally, so the number
on screen only ever comes from real rounds.

The tally is kept in the browser's local storage, so a reload keeps it. "Take back last round"
fixes a wrong tap; "Start over" (tap twice) clears it.

## Files

- `index.html`: the page. The tally has test id `hide-tally`, with `data-found` and `data-hidden`.
- `main.js`: the socket and the buttons.
- `tally.js`: the rules, with no page code in it.
- `tally.test.mjs`: tests for the rules.

## Run it

It is plain HTML and JavaScript modules; no build step is needed. It connects to the brain at
`ws://<the page's host>:8765/ws` (CONTRACTS.md section 2). To point it somewhere else, add
`?ws=ws://127.0.0.1:8765/ws` to the address.

```
node --test web/src/game/tally.test.mjs
```
