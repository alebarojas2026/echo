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

`npm run build` puts it in `web/dist/game/`, so the board serves it at `http://192.168.77.2:8080/game/`
(and the phone page at `/phone/`). In development, `npm run dev` serves it at `/src/game/`. It connects to the brain at
`ws://<the page's host>:8765/ws` (CONTRACTS.md section 2). To point it somewhere else, add
`?ws=ws://127.0.0.1:8765/ws` to the address.

```
node --test web/src/game/tally.test.mjs
```

## Caregiver phone page (`phone/`)

A page for a judge to hold: one full-screen card that follows the brain's state.

- **Calm:** "Someone is in the Chair zone." (or "Nobody is in the room."), with how long there has
  been no movement while the alert is counting.
- **Alert:** "No movement in the Bathroom for 10 s." when the no-movement alert fires. It plays a
  short chime once and vibrates where the browser can (not on iPhone). A check-in or a reset takes
  it back to calm.
- **Armed:** "Armed." while the space should be empty. The card turns to INTRUSION, with the chime, only on the
  board's `intrusion` event, never from `pred`, and stays until `disarmed`, `reset` or a state that is not armed.
  A `passed_by` event is one calm line under the card for 5 s, with no chime. A device in `state.tamper` is named
  under the card from /nodes.json ("East beacon unplugged while armed.").
- **A phone that opens the page late** has not seen an earlier `intrusion` (the state does not carry one), so it
  shows "Armed." until the board's next event. It never guesses an alarm.
- **NO DATA / SENSOR BLIND / getting ready:** shown as such, never as an empty room.
- The time of the last check-in sits under the card.
- iPhone only lets a page make sound after a tap, so the page starts with a "Tap to turn on sound"
  button. The chime is two tones made in the browser; there is no sound file.

It reads the same socket as the screen (`ws://<the page's host>:8765/ws`, `?ws=<url>` to override).
`?mock=calm|counting|alert|checkin|empty|blind|armed|intrusion|passed|tamper` shows one card without a board. Colours come from
the shared tokens in `web/src/room/room.css`.

```
node --test web/src/game/phone/card.test.mjs
```
