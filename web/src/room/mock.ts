import type { Advice, Alert, Checkin, CmdMsg, LinkState, Narration, ObjectMark, Pred, StateMsg, Teacher, Xray } from './contract'
import type { Transport } from './feed'
import { demoScene } from './demo'
import { HOME_SPOT, LINK_IDS, nodePosition, parseLinkId, zoneAt } from './frame'

// Mock state messages (CONTRACTS.md v2 section 5) for building the screen without the board.
// src is "sim" so nothing here can pass for live, and measured numbers (train time, ms per decision,
// before/after dBm) stay null so the panels show "__".
//
// ?mock= tour (default) | demo | still | checkin | camera | between | object | blind | empty | waiting | stall
//   tour    someone walks a loop through the four zones, pausing in each
//   still   someone stays still in zone 4, the no-movement alert counts up to 10 s and fires, and after
//           14 s a wave check-in clears it; this repeats
//   checkin someone stands still in zone 4 for 5 s, then waves (a check-in) and the count stops; every 15 s
//   camera  the tour with the camera on and its label (teacher) following for 8 s, then the camera off; every 16 s
//   between someone stands on the line between zones 3 and 4, so zone_set has both
//   object  an object sits next to the router, with advice to move the router
//   blind   the radio fails: health blind, pred null
//   empty   nobody in the room
//   waiting the brain is up but no link has a reading yet: links [], pred and xray null
//   stall   states for 1 s, then nothing (NO DATA)
//   demo    the whole demo on a 90 s loop, in the planned running order (see demo.ts)

export type MockScenario =
  | 'tour' | 'still' | 'checkin' | 'camera' | 'between' | 'object' | 'blind' | 'empty' | 'waiting' | 'stall' | 'demo'

const SEG_MS = 5000 // tour: 3 s walking, 2 s still, per zone
const XRAY = { w: 10, h: 10, cell_m: 0.24, origin_m: [-0.2, -0.2] as [number, number] }
const OBJECT_XY: [number, number] = [1.0, 0.2]

/** The person's floor point at time t in the tour, and whether they're walking. */
export function tourAt(tMs: number): { xy: [number, number]; moving: boolean } {
  const k = Math.floor(tMs / SEG_MS)
  const f = (tMs % SEG_MS) / SEG_MS
  const walking = f < 0.6
  const u = walking ? smooth(f / 0.6) : 1
  const a = Math.PI / 4 + (k + u) * (Math.PI / 2)
  const r = Math.SQRT1_2 // the circle through the four zone centres
  return { xy: [1 + r * Math.cos(a), 1 + r * Math.sin(a)], moving: walking }
}

function smooth(x: number) {
  return x * x * (3 - 2 * x)
}

/** Distance from a floor point to the floor line under a link. */
function distToLink(xy: [number, number], id: string, router: string): number {
  const parts = parseLinkId(id)
  if (!parts) return Infinity
  const [ax, ay] = nodePosition(parts.tx, router)
  const [bx, by] = nodePosition(parts.rx, router)
  const dx = bx - ax
  const dy = by - ay
  const s = Math.max(0, Math.min(1, ((xy[0] - ax) * dx + (xy[1] - ay) * dy) / (dx * dx + dy * dy)))
  return Math.hypot(xy[0] - (ax + s * dx), xy[1] - (ay + s * dy))
}

function blob(xy: [number, number] | null, peak: number): number[] {
  const out: number[] = []
  for (let iy = 0; iy < XRAY.h; iy++) {
    for (let ix = 0; ix < XRAY.w; ix++) {
      const cx = XRAY.origin_m[0] + (ix + 0.5) * XRAY.cell_m
      const cy = XRAY.origin_m[1] + (iy + 0.5) * XRAY.cell_m
      const d2 = xy ? (cx - xy[0]) ** 2 + (cy - xy[1]) ** 2 : Infinity
      out.push(Number((peak * Math.exp(-d2 / (2 * 0.18 ** 2))).toFixed(2)))
    }
  }
  return out
}

function zoneSet(xy: [number, number]): number[] {
  const zone = zoneAt(xy[0], xy[1])
  const set = [zone]
  if (Math.abs(xy[0] - 1) < 0.15) set.push(zoneAt(2 - xy[0], xy[1]))
  else if (Math.abs(xy[1] - 1) < 0.15) set.push(zoneAt(xy[0], 2 - xy[1]))
  return set
}

const CHECKIN_LINK = 'pi5>unoq:wifi'

/** The no-movement count and the last check-in at tMs. Check-in times come from `start` (epoch ms when
 *  the mock began), so each one appears once and then stays the same, like the board's last check-in. */
export function stillTimeline(scenario: MockScenario, tMs: number, start: number): { alert: Alert; checkin: Checkin | null; stillS: number } {
  const none: Alert = { state: 'none', zone: null, still_s: 0, limit_s: null }
  const wave = (t: number): Checkin => ({ t: Math.round(t), link: CHECKIN_LINK })
  if (scenario === 'still') {
    const k = Math.floor(tMs / 14000)
    const stillS = (tMs % 14000) / 1000
    const alert: Alert = { state: stillS >= 10 ? 'check_on' : 'counting', zone: 4, still_s: Number(stillS.toFixed(1)), limit_s: 10 }
    return { alert, checkin: k > 0 ? wave(start + k * 14000) : null, stillS }
  }
  if (scenario === 'checkin') {
    const k = Math.floor(tMs / 15000)
    const phase = tMs % 15000
    if (phase < 5000) {
      const stillS = phase / 1000
      const alert: Alert = { state: 'counting', zone: 4, still_s: Number(stillS.toFixed(1)), limit_s: 10 }
      return { alert, checkin: k > 0 ? wave(start + (k - 1) * 15000 + 5000) : null, stillS }
    }
    return { alert: none, checkin: wave(start + k * 15000 + 5000), stillS: 0 }
  }
  return { alert: none, checkin: null, stillS: 0 }
}

/** Everything a mock state is built from: who and what is where, and what the board has decided. */
export interface Scene {
  person: { xy: [number, number]; moving: boolean } | null
  object: [number, number] | null
  router: string
  blind: boolean
  alert: Alert
  checkin: Checkin | null
  stillS: number
  cam: 'on' | 'off'
  /** Advice about the object by the router. It only reaches the state while the Wi-Fi link is dropping. */
  advice: boolean
  narration: Narration | null
}

export function mockState(scenario: MockScenario, seq: number, tMs: number, router = HOME_SPOT, start = Date.now() - tMs): StateMsg {
  if (scenario === 'waiting') return { ...emptyState(seq, router), links: [] }
  if (scenario === 'demo') return buildState(seq, tMs, demoScene(tMs, start))
  const standing: Partial<Record<MockScenario, [number, number]>> = { still: [1.5, 0.5], checkin: [1.5, 0.5], between: [1.06, 0.55] }
  const walking = scenario === 'tour' || scenario === 'camera'
  const person = walking ? tourAt(tMs) : standing[scenario] ? { xy: standing[scenario]!, moving: false } : null
  const { alert, checkin, stillS } = stillTimeline(scenario, tMs, start)
  const object = scenario === 'object' ? OBJECT_XY : null
  return buildState(seq, tMs, {
    person, object, router, alert, checkin, stillS,
    blind: scenario === 'blind',
    cam: scenario === 'camera' && tMs % 16000 < 8000 ? 'on' : 'off',
    advice: !!object,
    narration: null,
  })
}

/** The drop this mock puts on a link from a person and an object, with a little steady wobble. */
function linkDrop(id: string, i: number, person: [number, number] | null, object: [number, number] | null, router: string, tMs: number) {
  const near = (xy: [number, number] | null, db: number) => (xy ? db * Math.exp(-((distToLink(xy, id, router) / 0.2) ** 2)) : 0)
  return near(person, 7) + near(object, 9) + 0.3 * Math.sin(tMs / 700 + i)
}

export function buildState(seq: number, tMs: number, scene: Scene): StateMsg {
  const { person, object, router, blind } = scene
  const links: LinkState[] = LINK_IDS.map((id, i) => {
    const drop = linkDrop(id, i, person?.xy ?? null, object, router, tMs)
    const status = blind && id === 'east>unoq:ble' ? 'blind' : 'ok'
    return {
      id,
      dbm: Number((-58 - i - drop).toFixed(1)),
      base_dbm: -58 - i,
      drop_db: Number(drop.toFixed(1)),
      rate_hz: status === 'blind' ? 0 : 9.4,
      expected_hz: 9.5,
      status,
      why: 0,
    }
  })
  const top = [...links].sort((a, b) => (b.drop_db ?? 0) - (a.drop_db ?? 0))
  for (const l of top.slice(0, 2)) l.why = 0.5

  let pred: Pred | null = null
  if (!blind && router === HOME_SPOT) {
    const set = person ? zoneSet(person.xy) : []
    const zone = set[0] ?? 0
    const probs = [0, 0, 0, 0, 0]
    if (zone) {
      probs[zone] = set.length > 1 ? 0.55 : 0.85
      if (set[1]) probs[set[1]] = 0.35
    }
    probs[0] = Number((1 - probs.reduce((a, b) => a + b, 0)).toFixed(2))
    pred = {
      present: !!person,
      // With only the tray in the square the board says "an object", not "nobody".
      kind: person ? 'person' : object ? 'object' : 'none',
      zone,
      zone_set: set,
      probs,
      motion: person ? (person.moving ? 'moving' : 'still') : null, // present:false -> motion null
      still_s: Number(scene.stillS.toFixed(1)),
      why: person ? top.slice(0, 2).map((l) => l.id) : [],
    }
  }

  const xray: Xray = {
    ...XRAY,
    // People (walking or still) are in moving_db; only objects are in static_db (contract section 6).
    moving_db: blob(person?.xy ?? null, person?.moving ? 6 : 4),
    static_db: blob(object, 8),
    n_links: 6,
  }
  const objects: ObjectMark[] = object ? [{ xy_m: object, near: 'pi5', since_s: Number((tMs / 1000).toFixed(1)), drop_db: 9 }] : []
  const wifiNow = links.find((l) => l.id === 'pi5>unoq:wifi')!.dbm!
  // before_dbm is frozen when the router moves: the reading at S-home with the object there.
  const wifiHome = Number((-58 - linkDrop('pi5>unoq:wifi', 0, null, object, HOME_SPOT, 0)).toFixed(1))
  // Contract section 6: advice only while pi5>unoq:wifi is dropping by 3 dB or more.
  const wifiDrop = links.find((l) => l.id === 'pi5>unoq:wifi')!.drop_db ?? 0
  const advice: Advice | null =
    object && scene.advice && wifiDrop >= 3
      ? {
          id: 'a1', cause: 'obstruction', near: 'pi5', xy_m: object, link: 'pi5>unoq:wifi', to_spot: 'S-W30',
          // before_dbm is this mock's own wifi reading; dist_change_m comes from the spot geometry.
          move_m: [-0.3, 0], dist_change_m: spotDistanceChange('S-W30'), why: ['pi5>unoq:wifi'],
          before_dbm: router === HOME_SPOT ? wifiNow : wifiHome,
          after_dbm: null,
          text: 'An object next to the router is blocking its link to the receiver. Move the router 30 cm west.',
        }
      : null
  const teacher: Teacher | null =
    scene.cam === 'on'
      ? pred ? { present: pred.present, zone: pred.zone, motion: pred.motion } : { present: false, zone: 0, motion: null }
      : null

  return {
    v: 2, type: 'state', t: Date.now(), seq, src: 'sim', cam: scene.cam, router, links,
    health: blind ? { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' } : { status: 'ok', blind: [], reason: null },
    pred, objects, xray,
    alert: scene.alert, checkin: scene.checkin, advice, narration: scene.narration, teacher,
    model: UNTRAINED,
    board: NO_BOARD,
  }
}

/** A Transport that plays a scenario at 10 states a second and answers router commands. */
export function createMockSource(scenario: MockScenario): Transport {
  let router = HOME_SPOT
  return {
    start(deliver, setConnected) {
      const t0 = performance.now()
      const start = Date.now()
      let seq = 0
      setConnected(true)
      const id = setInterval(() => {
        const t = performance.now() - t0
        if (scenario === 'stall' && t > 1000) return clearInterval(id)
        deliver(mockState(scenario, ++seq, t, router, start))
      }, 100)
    },
    send(msg: CmdMsg) {
      if (msg.cmd === 'router_moved' && typeof msg.args.spot === 'string') router = msg.args.spot
      if (msg.cmd === 'router_home') router = HOME_SPOT
    },
  }
}

/** Before any reading: what the brain sends when it's up but the radios haven't reported. */
function emptyState(seq: number, router: string): StateMsg {
  return {
    v: 2, type: 'state', t: Date.now(), seq, src: 'sim', cam: 'off', router, links: [],
    health: { status: 'ok', blind: [], reason: null }, pred: null, objects: [], xray: null,
    alert: { state: 'none', zone: null, still_s: 0, limit_s: null }, checkin: null, advice: null,
    narration: null, teacher: null, board: NO_BOARD, model: UNTRAINED,
  }
}

/** Training time and decision time are measurements, so the mock says "not trained" and leaves them null.
 *  (The contract now also allows trained with null timings; the schema in contracts/ doesn't yet.) */
const UNTRAINED = { trained: false, ver: null, train_s: null, ms_per_decision: null, windows: 0, train_sessions: [], training: null }

/** The board's readings are measurements; the mock has none. */
const NO_BOARD = { cpu_temp_c: null, cpu_mhz: null, cpu_pct: null }

/** How much longer the router-to-receiver link gets when the router moves from S-home to `spot`, in metres. */
function spotDistanceChange(spot: string): number {
  const [rx, ry] = nodePosition('unoq', HOME_SPOT)
  const [hx, hy] = nodePosition('pi5', HOME_SPOT)
  const [sx, sy] = nodePosition('pi5', spot)
  return Number((Math.hypot(sx - rx, sy - ry) - Math.hypot(hx - rx, hy - ry)).toFixed(3))
}
