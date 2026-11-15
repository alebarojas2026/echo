import type { Alert, Checkin, Narration } from './contract'
import { HOME_SPOT, LINK_IDS, TRAY_SPOTS, ZONES, floorSize, routerId, zoneCenter } from './frame'
import type { Scene } from './mock'

// ?mock=demo: the whole demo as a 90 s loop, in the running order of plan/ui-research/03 section 4, so the kiosk
// has an attract screen and the video and rehearsals have a repeatable take. Everything is mock data (src "sim").
//
// Zones and spots come from the layout in use: "zone A" is the last zone (the square's 4, the desk's Right) and
// "zone B" the one north of it on the square (2), else the first zone (the desk's Left).
//
//   0-4    the floor is empty, the setup camera is on
//   4-8    someone walks into zone A from the south
//   8-25   they stand still; the no-movement alert counts from 0 and fires at 10 s
//   25     they wave: a check-in clears the alert
//   34     the camera is unplugged; from here on it's radio only
//   38-47  they walk to zone B, then step out the nearer side
//   48     the tray goes on T1 next to the router: an object, not a person
//   57     advice: move the router 30 cm west
//   62     the router is moved (pred pauses while it's off S-home)
//   62+    the link no longer drops, so the advice clears; the result comes in the narration (73 s)
//   82     a recap sentence closes the loop
//   90     the loop starts again

export const DEMO_MS = 90_000

/** The demo's places for the layout in use: zone A (the alert), zone B, their middles, the tray and the exit. */
function places() {
  const a = ZONES[ZONES.length - 1].id
  const b = ZONES.some((z) => z.id === a - 2) ? a - 2 : ZONES[0].id
  const inA = zoneCenter(a)!
  const inB = zoneCenter(b)!
  const [fw] = floorSize()
  const exit: [number, number] = [inB[0] > fw / 2 ? fw + 0.35 : -0.35, inB[1]]
  const wifi = LINK_IDS.find((id) => id.startsWith(`${routerId()}>`) && id.endsWith(':wifi')) ?? LINK_IDS[0]
  return { a, b, inA, inB, exit, tray: [TRAY_SPOTS[0][0], TRAY_SPOTS[0][1]] as [number, number], wifi }
}

function lerp(a: [number, number], b: [number, number], u: number): [number, number] {
  const s = u * u * (3 - 2 * u)
  return [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s]
}

function zoneName(zone: number): string {
  return `zone ${zone} (${ZONES.find((z) => z.id === zone)?.name ?? ''})`
}

/** Template sentences, each arriving about 6 s after its event, the way the narrator would send them. */
const lines = (a: number): [number, string, string][] => [
  [10, 'enter', `Someone just walked into ${zoneName(a)}.`],
  [24, 'alert_on', `No movement for 10 seconds in ${zoneName(a)}.`],
  [31, 'checkin', `Check-in received from ${zoneName(a)}.`],
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
  const { a, inA, inB, exit, tray, wifi } = places()

  let person: Scene['person'] = null
  if (s >= 4 && s < 8) person = { xy: lerp([inA[0], 0.02], inA, (s - 4) / 4), moving: true }
  else if (s >= 8 && s < 25) person = { xy: inA, moving: false }
  else if (s >= 25 && s < 38) person = { xy: inA, moving: true } // waving, then reaching for the camera joint
  else if (s >= 38 && s < 42) person = { xy: lerp(inA, inB, (s - 38) / 4), moving: true }
  else if (s >= 42 && s < 44) person = { xy: inB, moving: false }
  else if (s >= 44 && s < 47) person = { xy: lerp(inB, exit, (s - 44) / 3), moving: true }

  const still = s >= 8 && s < 25 ? s - 8 : 0
  const alert: Alert =
    s >= 8 && s < 25
      ? { state: still >= 10 ? 'check_on' : 'counting', zone: a, still_s: Number(still.toFixed(1)), limit_s: 10 }
      : { state: 'none', zone: null, still_s: 0, limit_s: null }
  const checkin: Checkin | null = s >= 25 ? { t: base + 25_000, link: wifi } : null

  let narration: Narration | null = null
  for (const [at, kind, text] of lines(a)) {
    if (s >= at) narration = { text, event_id: `demo-${kind}`, t: base + at * 1000, source: 'template', gen_ms: 0 } // templates take no time to write
  }

  return {
    person,
    object: s >= 48 ? tray : null,
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
