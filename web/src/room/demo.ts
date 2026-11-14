import type { Alert, Checkin, Narration } from './contract'
import { HOME_SPOT, ZONES } from './frame'
import type { Scene } from './mock'

// ?mock=demo: the whole demo as a 90 s loop, in the running order of plan/ui-research/03 section 4, so the kiosk
// has an attract screen and the video and rehearsals have a repeatable take. Everything is mock data (src "sim").
//
//   0-4    the square is empty, the setup camera is on
//   4-8    someone walks into zone 4 from the south
//   8-25   they stand still; the no-movement alert counts from 0 and fires at 10 s
//   25     they wave: a check-in clears the alert
//   34     the camera is unplugged; from here on it's radio only
//   38-47  they walk to zone 2, then step out east
//   48     the tray goes on T1 next to the router: an object, not a person
//   57     advice: move the router 30 cm west
//   62     the router is moved (pred pauses while it's off S-home)
//   62+    the link no longer drops, so the advice clears; the result comes in the narration (73 s)
//   82     a recap sentence closes the loop
//   90     the loop starts again

export const DEMO_MS = 90_000

const T1: [number, number] = [1.0, 0.2]
const IN_4: [number, number] = [1.5, 0.5]
const IN_2: [number, number] = [1.5, 1.5]

function lerp(a: [number, number], b: [number, number], u: number): [number, number] {
  const s = u * u * (3 - 2 * u)
  return [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s]
}

function zoneName(zone: number): string {
  return `zone ${zone} (${ZONES.find((z) => z.id === zone)?.name ?? ''})`
}

/** Template sentences, each arriving about 6 s after its event, the way the narrator would send them. */
const LINES: [number, string, string][] = [
  [10, 'enter', `Someone just walked into ${zoneName(4)}.`],
  [24, 'alert_on', `No movement for 10 seconds in ${zoneName(4)}.`],
  [31, 'checkin', `Check-in received from ${zoneName(4)}.`],
  [40, 'cam_off', 'Setup is done; sensing now runs on radio alone.'],
  [54, 'object_on', 'An object, not a person, is next to the router.'],
  [73, 'advice_result', 'Moving the router made its link to the receiver stronger.'],
  // The end-of-demo recap: up to 3 sentences and 45 words (contract section 6).
  [82, 'recap', 'Someone walked in, stood still until the no-movement alert, and waved to check in. ' +
    'Then the camera came off and the radio kept up. It told the tray from a person and found a better router spot.'],
]

export function demoScene(tMs: number, start: number): Scene {
  const phase = tMs % DEMO_MS
  const base = start + (tMs - phase) // epoch ms when this loop began
  const s = phase / 1000

  let person: Scene['person'] = null
  if (s >= 4 && s < 8) person = { xy: lerp([1.5, 0.02], IN_4, (s - 4) / 4), moving: true }
  else if (s >= 8 && s < 25) person = { xy: IN_4, moving: false }
  else if (s >= 25 && s < 38) person = { xy: IN_4, moving: true } // waving, then reaching for the camera joint
  else if (s >= 38 && s < 42) person = { xy: lerp(IN_4, IN_2, (s - 38) / 4), moving: true }
  else if (s >= 42 && s < 44) person = { xy: IN_2, moving: false }
  else if (s >= 44 && s < 47) person = { xy: lerp(IN_2, [2.35, 1.5], (s - 44) / 3), moving: true }

  const still = s >= 8 && s < 25 ? s - 8 : 0
  const alert: Alert =
    s >= 8 && s < 25
      ? { state: still >= 10 ? 'check_on' : 'counting', zone: 4, still_s: Number(still.toFixed(1)), limit_s: 10 }
      : { state: 'none', zone: null, still_s: 0, limit_s: null }
  const checkin: Checkin | null = s >= 25 ? { t: base + 25_000, link: 'pi5>unoq:wifi' } : null

  let narration: Narration | null = null
  for (const [at, kind, text] of LINES) {
    if (s >= at) narration = { text, event_id: `demo-${kind}`, t: base + at * 1000, source: 'template', gen_ms: 0 } // templates take no time to write
  }

  return {
    person,
    object: s >= 48 ? T1 : null,
    router: s >= 62 ? 'S-W30' : HOME_SPOT,
    blind: false,
    alert,
    checkin,
    stillS: still,
    cam: s < 34 ? 'on' : 'off',
    // Advice shows from 57 s; once the router moves the link stops dropping and the advice clears (contract).
    advice: s >= 57,
    narration,
  }
}
