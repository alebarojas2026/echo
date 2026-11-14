# Radio Sight: 3-Minute Desk Demo

Each judge spends about 3 minutes at our desk spot. This is the script for that visit: four moments that land fastest, a 20-second opening and a 15-second close. The 5-minute run in `demo-runbook.md` and `pitch.md` stays the finalist script.

The layout is being redesigned for the desk spot, so this script only says "the sensing area" and "the nodes". Every proof number stays `__` until it is measured and in `PROOF.md`.

Before the first judge: the setup in `demo-runbook.md` is done (baseline, training), the router is on its home spot, the camera is plugged in, and the screen says LIVE with the headline "Nobody is here".

## The 3 minutes

Each line is one timed step: what the presenter says, what the judge does, and what the screen shows.

| Time | Presenter says | Judge does | Screen shows |
|---|---|---|---|
| 0:00-0:20 | "This is Radio Sight: Wi-Fi that understands the room. The radio links between these nodes show where a person is and whether they're moving. Every decision runs on this UNO Q, on the Dragonwing CPU, and no image is ever saved." | Stands at the desk. | "Nobody is here", LIVE, Camera on. |
| 0:20-0:45 | "Step into the sensing area and walk around." | Steps in and walks. | Their figure appears in their zone and follows them; the headline says "Moving" and the zone. |
| 0:45-1:00 | "Now walk to the bathroom corner." | Walks to the Bathroom zone. | The figure glides there; "Moving in the bathroom". |
| 1:00-1:25 | "Stand still, as if you'd stopped moving. In the bathroom the board waits ten seconds." | Stands still. | "Still in the bathroom", the count, then the no-movement alert with the words "No movement". |
| 1:25-1:45 | "Give it a wave, like this." | Waves without leaving the zone. | The check-in with its word, and the alert clears. |
| 1:45-2:20 | "The camera only taught the radio during setup. Pull its cable." | Pulls the camera's cable. | "Camera unplugged · radio only"; the figure keeps following them. |
| 2:20-2:45 | "Walk out of the area." | Walks out. | "Nobody is here", on radio alone. |
| 2:45-3:00 | "Zone accuracy on walkers it never trained on: __. One decision takes __ ms on the board. Images stored: __. Bytes sent off our network: __. Radio Sight: room-aware, and private by design." | Looks at the proof strip. | The proof strip, with `__` for anything not yet measured. |

Before the cable moment, check the screen says "Camera on". If it doesn't yet (it was plugged back in during the reset), skip the pull and say the camera only taught the radio during setup. If a moment doesn't show (NO DATA or SENSOR BLIND), say what the screen says and move to the next line; never call it an empty room. Recovery steps are in `demo-runbook.md`.

## If the judge has time

These moments move out of the 3 minutes. Offer them only when the judge stays longer; they are all in the 5-minute run.

- **The tray and the router advice:** the tray goes by the router, the screen says "An object, not a person", and the advice to move the router appears while its Wi-Fi link is dropping. Before and after values stay `__` until measured. Putting things back takes longer than a reset: the tray comes off and the router returns home before `router_home` is sent.
- **The recap:** after the reset, a short summary of the visit appears on the screen, written on the board.
- **The game:** "Can you hide from Wi-Fi?" at `/game/`, and the caregiver page at `/phone/` on a phone.

## Reset between judges (about 20 seconds)

| Time | Step |
|---|---|
| 0:00-0:05 | The judge has walked out; the sensing area is empty. |
| 0:05-0:12 | Alexander plugs the camera back in. Don't wait for it: the camera app restarts on its own and the screen says "Camera on" again once frames flow. |
| 0:12-0:15 | The operator presses "Reset demo" (the O key shows the controls). The alert, still count, check-in, advice and narration clear. |
| 0:15-0:20 | Check the screen: LIVE, "Nobody is here", no NO DATA or SENSOR BLIND. The recap of the last visit may show; that's expected. |

If the tray and router moment ran, put the tray away and the router back home and send `router_home` before this reset; that's outside the 20 seconds.
