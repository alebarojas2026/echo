import type { Advice, Alert, Checkin, CmdMsg, EventMsg, HallLink, LinkState, Narration, ObjectMark, Pred, StateMsg, Teacher, Xray } from './contract'
import type { Transport } from './feed'
import { DEMO_MS, demoScene } from './demo'
import { HALL_BEACONS, HOME_SPOT, LINK_IDS, SIZE_M, STRIP_M, TRAY_SPOTS, ZONES, floorSize, nodePosition, parseLinkId, routerId, zoneAt, zoneCenter } from './frame'

// Mock state messages (CONTRACTS.md v2 section 5) for building the screen without the board.
// src is "sim" so nothing here can pass for live, and measured numbers (train time, ms per decision,
// before/after dBm) stay null so the panels show "__".
//
// ?mock= tour (default) | demo | still | checkin | camera | between | object | blind | empty | waiting | stall | power
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
//   power   the tour, with the East beacon switched off for 6 s in every 16 (see powerOff)
//   demo    the whole demo on a 90 s loop, in the planned running order (see demo.ts)

const SCENARIOS = ['tour', 'still', 'checkin', 'camera', 'between', 'object', 'blind', 'empty', 'waiting', 'stall', 'demo', 'power'] as const
export type MockScenario = (typeof SCENARIOS)[number]

/** The scenario ?mock= names; anything else (?mock=1, or no name) is the tour. */
export function mockScenario(name: string | null): MockScenario {
  return (SCENARIOS as readonly string[]).includes(name ?? '') ? (name as MockScenario) : 'tour'
}

/** ?mock=power: someone walks the tour while the East beacon is switched off for 6 s in every 16. Its links go
 *  stale, then blind after 3 s (SENSOR BLIND), and the beacon fades to "not heard" until it is back. Hall beacon
 *  J (when nodes.json has one) is off for the first 4 s of each cycle, so it turns up as a new beacon. */
export function hallOff(tMs: number): string[] {
  return tMs % 16000 < 4000 ? ['j'] : []
}

export function powerOff(tMs: number): { nodes: string[]; forS: number } | undefined {
  const cycle = tMs % 16000
  return cycle >= 6000 && cycle < 12000 ? { nodes: ['east'], forS: (cycle - 6000) / 1000 } : undefined
}

// Everything below is built from the layout in use (nodes.json): its zones, links, tray spot and size.
const SEG_MS = 5000 // tour: 3 s walking, 2 s still, per zone

/** The X-ray grid the brain sends for this layout: 0.24 m cells on the square, 0.125 m on the desk, 0.2 m past
 *  every side (10 x 10 on the square, 16 x 12 on the desk). */
function xrayGrid() {
  const cell = STRIP_M ? 0.125 : 0.24
  return { w: Math.round((SIZE_M[0] + 0.4) / cell), h: Math.round((SIZE_M[1] + 0.4) / cell), cell_m: cell, origin_m: [-0.2, -0.2] as [number, number] }
}

/** The tray's floor point: nodes.json's first tray spot. */
function trayXy(): [number, number] {
  return [TRAY_SPOTS[0][0], TRAY_SPOTS[0][1]]
}

/** The zone the still and check-in scenes use: the last one (the square's Bathroom, the desk's Right). */
export function alertZone(): number {
  return ZONES[ZONES.length - 1].id
}

/** The router's Wi-Fi link to the receiver: the check-in link and the one advice watches. */
function wifiLink(): string {
  return LINK_IDS.find((id) => id.startsWith(`${routerId()}>`) && id.endsWith(':wifi')) ?? LINK_IDS[0]
}

/** A point in the one spot, a quarter of its width east (1) or west (-1) of its middle. */
function spotStep(d: number): [number, number] {
  const [x, y] = zoneCenter(ZONES[0].id)!
  return [x + (d * floorSize()[0]) / 4, y]
}

/** The tour's stops: each zone's centre, anticlockwise around the floor from the north-east. */
function tourStops(): { xy: [number, number]; angle: number }[] {
  const [fw, fh] = floorSize()
  const at = (xy: [number, number]) => (Math.atan2(xy[1] - fh / 2, xy[0] - fw / 2) - Math.PI / 4 + 4 * Math.PI) % (2 * Math.PI)
  // One spot: there is nowhere else to walk to, so the stops are a step either side of its middle.
  const stops = ZONES.length === 1 ? [spotStep(-1), spotStep(1)] : ZONES.map((z) => zoneCenter(z.id)!)
  return stops.map((xy) => ({ xy, angle: at(xy) })).sort((a, b) => a.angle - b.angle)
}

/** The person's floor point at time t in the tour, and whether they're walking. With three or more zones they
 *  walk the circle through the zone centres; with two, straight back and forth. */
export function tourAt(tMs: number): { xy: [number, number]; moving: boolean } {
  const k = Math.floor(tMs / SEG_MS)
  const f = (tMs % SEG_MS) / SEG_MS
  const walking = f < 0.6
  const u = walking ? smooth(f / 0.6) : 1
  const stops = tourStops()
  const from = stops[k % stops.length]
  const to = stops[(k + 1) % stops.length]
  if (stops.length < 3) return { xy: [from.xy[0] + (to.xy[0] - from.xy[0]) * u, from.xy[1] + (to.xy[1] - from.xy[1]) * u], moving: walking }
  const [fw, fh] = floorSize()
  const r = Math.hypot(from.xy[0] - fw / 2, from.xy[1] - fh / 2)
  const turn = (to.angle - from.angle + 2 * Math.PI) % (2 * Math.PI)
  const a = from.angle + Math.PI / 4 + u * turn
  return { xy: [fw / 2 + r * Math.cos(a), fh / 2 + r * Math.sin(a)], moving: walking }
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
  const grid = xrayGrid()
  const out: number[] = []
  for (let iy = 0; iy < grid.h; iy++) {
    for (let ix = 0; ix < grid.w; ix++) {
      const cx = grid.origin_m[0] + (ix + 0.5) * grid.cell_m
      const cy = grid.origin_m[1] + (iy + 0.5) * grid.cell_m
      const d2 = xy ? (cx - xy[0]) ** 2 + (cy - xy[1]) ** 2 : Infinity
      out.push(Number((peak * Math.exp(-d2 / (2 * 0.18 ** 2))).toFixed(2)))
    }
  }
  return out
}

/** The zone a point is in, plus the neighbouring zone when it is within 15 cm of their shared line. */
function zoneSet(xy: [number, number]): number[] {
  const zone = zoneAt(xy[0], xy[1])
  if (!zone) return []
  for (const [dx, dy] of [[0.15, 0], [-0.15, 0], [0, 0.15], [0, -0.15]]) {
    const near = zoneAt(xy[0] + dx, xy[1] + dy)
    if (near && near !== zone) return [zone, near]
  }
  return [zone]
}

/** The no-movement count and the last check-in at tMs. Check-in times come from `start` (epoch ms when
 *  the mock began), so each one appears once and then stays the same, like the board's last check-in. */
export function stillTimeline(scenario: MockScenario, tMs: number, start: number): { alert: Alert; checkin: Checkin | null; stillS: number } {
  const none: Alert = { state: 'none', zone: null, still_s: 0, limit_s: null }
  const wave = (t: number): Checkin => ({ t: Math.round(t), link: wifiLink() })
  const zone = alertZone()
  if (scenario === 'still') {
    const k = Math.floor(tMs / 14000)
    const stillS = (tMs % 14000) / 1000
    const alert: Alert = { state: stillS >= 10 ? 'check_on' : 'counting', zone, still_s: Number(stillS.toFixed(1)), limit_s: 10 }
    return { alert, checkin: k > 0 ? wave(start + k * 14000) : null, stillS }
  }
  if (scenario === 'checkin') {
    const k = Math.floor(tMs / 15000)
    const phase = tMs % 15000
    if (phase < 5000) {
      const stillS = phase / 1000
      const alert: Alert = { state: 'counting', zone, still_s: Number(stillS.toFixed(1)), limit_s: 10 }
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
  /** Devices switched off, and for how long: their links read nothing (stale, then blind after 3 s). */
  off?: { nodes: string[]; forS: number }
  /** Hall beacons switched off: their hall rows read nothing (stale). */
  hallOff?: string[]
  /** Advice about the object by the router. It only reaches the state while the Wi-Fi link is dropping. */
  advice: boolean
  narration: Narration | null
}

export function mockState(scenario: MockScenario, seq: number, tMs: number, router = HOME_SPOT, start = Date.now() - tMs): StateMsg {
  if (scenario === 'waiting') return { ...emptyState(seq, router), links: [] }
  if (scenario === 'demo') return buildState(seq, tMs, demoScene(tMs, start))
  // Still and check-in stand in the alert zone's middle; "between" stands just past the line between the last two
  // zones (the square's 3 and 4, the desk's Left and Right).
  const middle = zoneCenter(alertZone())!
  // (One spot has no line to stand on: "between" is then a step off its middle.)
  const prev = ZONES.length > 1 ? zoneCenter(ZONES[ZONES.length - 2].id)! : spotStep(-1)
  const between: [number, number] = [(middle[0] + prev[0]) / 2 + 0.06, (middle[1] + prev[1]) / 2 + 0.05]
  const standing: Partial<Record<MockScenario, [number, number]>> = { still: middle, checkin: middle, between }
  const walking = scenario === 'tour' || scenario === 'camera' || scenario === 'power'
  const person = walking ? tourAt(tMs) : standing[scenario] ? { xy: standing[scenario]!, moving: false } : null
  const { alert, checkin, stillS } = stillTimeline(scenario, tMs, start)
  const object = scenario === 'object' ? trayXy() : null
  return buildState(seq, tMs, {
    person, object, router, alert, checkin, stillS,
    blind: scenario === 'blind',
    cam: scenario === 'camera' && tMs % 16000 < 8000 ? 'on' : 'off',
    advice: !!object,
    narration: null,
    off: scenario === 'power' ? powerOff(tMs) : undefined,
    hallOff: scenario === 'power' ? hallOff(tMs) : [],
  })
}

/** The drop this mock puts on a link from a person and an object, with a little steady wobble. */
function linkDrop(id: string, i: number, person: [number, number] | null, object: [number, number] | null, router: string, tMs: number) {
  const near = (xy: [number, number] | null, db: number) => (xy ? db * Math.exp(-((distToLink(xy, id, router) / 0.2) ** 2)) : 0)
  return near(person, 7) + near(object, 9) + 0.3 * Math.sin(tMs / 700 + i)
}

export function buildState(seq: number, tMs: number, scene: Scene): StateMsg {
  const { person, object, router } = scene
  const off = new Set(scene.off?.nodes ?? [])
  const offIds = LINK_IDS.filter((id) => {
    const p = parseLinkId(id)
    return !!p && (off.has(p.tx) || off.has(p.rx))
  })
  const offBlind = (scene.off?.forS ?? 0) >= 3
  const blind = scene.blind || (offBlind && offIds.length > 0)
  const blindIds = scene.blind ? ['east>unoq:ble'] : offBlind ? offIds : []
  const links: LinkState[] = LINK_IDS.map((id, i) => {
    const drop = linkDrop(id, i, person?.xy ?? null, object, router, tMs)
    const quiet = offIds.includes(id)
    const status = blindIds.includes(id) ? 'blind' : quiet ? 'stale' : 'ok'
    return {
      id,
      dbm: Number((-58 - i - drop).toFixed(1)),
      base_dbm: -58 - i,
      drop_db: Number(drop.toFixed(1)),
      rate_hz: status === 'blind' || quiet ? 0 : 9.4,
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
    const probs = [0, ...ZONES.map(() => 0)] // [empty, one per zone]
    if (zone) {
      probs[zone] = set.length > 1 ? 0.55 : 0.85
      if (set[1]) probs[set[1]] = 0.35
    }
    probs[0] = Number((1 - probs.reduce((a, b) => a + b, 0)).toFixed(2))
    pred = {
      present: zone > 0,
      // With only the tray in the square the board says "an object", not "nobody".
      kind: zone ? 'person' : object ? 'object' : 'none',
      zone,
      zone_set: set,
      probs,
      motion: zone ? (person!.moving ? 'moving' : 'still') : null, // present:false -> motion null
      still_s: Number(scene.stillS.toFixed(1)),
      why: zone ? top.slice(0, 2).map((l) => l.id) : [],
    }
  }

  const xray: Xray = {
    ...xrayGrid(),
    // People (walking or still) are in moving_db; only objects are in static_db (contract section 6).
    moving_db: blob(person?.xy ?? null, person?.moving ? 6 : 4),
    static_db: blob(object, 8),
    n_links: LINK_IDS.length,
  }
  const router0 = routerId()
  const wifi = wifiLink()
  const objects: ObjectMark[] = object ? [{ xy_m: object, near: router0, since_s: Number((tMs / 1000).toFixed(1)), drop_db: 9 }] : []
  const wifiNow = links.find((l) => l.id === wifi)!.dbm!
  // before_dbm is frozen when the router moves: the reading at S-home with the object there.
  const wifiHome = Number((-58 - linkDrop(wifi, 0, null, object, HOME_SPOT, 0)).toFixed(1))
  // Contract section 6: advice only while the router's Wi-Fi link is dropping by 3 dB or more.
  const wifiDrop = links.find((l) => l.id === wifi)!.drop_db ?? 0
  const advice: Advice | null =
    object && scene.advice && wifiDrop >= 3
      ? {
          id: 'a1', cause: 'obstruction', near: router0, xy_m: object, link: wifi, to_spot: 'S-W30',
          // before_dbm is this mock's own wifi reading; dist_change_m comes from the spot geometry.
          move_m: [-0.3, 0], dist_change_m: spotDistanceChange('S-W30'), why: [wifi],
          before_dbm: router === HOME_SPOT ? wifiNow : wifiHome,
          after_dbm: null,
          text: 'An object next to the router is blocking its link to the receiver. Move the router 30 cm west.',
        }
      : null
  // nodes.json's hall beacons, heard by the board: "movement on this path" while someone walks.
  const hall: HallLink[] = HALL_BEACONS.map((b) => {
    const quiet = (scene.hallOff ?? []).includes(b.node)
    return {
      id: `${b.node}>unoq:ble`, tx: b.node, rx: 'unoq', xy_m: b.xyz ? [b.xyz[0], b.xyz[1]] : null,
      activity: quiet ? 0 : person?.moving ? 0.6 : 0.05, moving: !quiet && !!person?.moving, rate_hz: quiet ? 0 : 6.5, stale: quiet,
    }
  })
  const teacher: Teacher | null =
    scene.cam === 'on'
      ? pred ? { present: pred.present, zone: pred.zone, motion: pred.motion } : { present: false, zone: 0, motion: null }
      : null

  return {
    v: 2, type: 'state', t: Date.now(), seq, src: 'sim', cam: scene.cam, router, links,
    health: blind ? { status: 'blind', blind: blindIds, reason: 'rate' } : { status: 'ok', blind: [], reason: null },
    pred, objects, xray,
    alert: scene.alert, checkin: scene.checkin, advice, narration: scene.narration, teacher,
    model: MOCK_MODEL,
    board: NO_BOARD,
    ...(hall.length ? { hall } : {}),
  }
}

/** A Transport that plays a scenario at 10 states a second and answers router commands. */
export function createMockSource(scenario: MockScenario): Transport {
  let router = HOME_SPOT
  let sendReset = () => {}
  return {
    start(deliver, setConnected) {
      const t0 = performance.now()
      const start = Date.now()
      let seq = 0
      let loop = 0
      // The brain's answer to the reset command (contract section 5): an event of kind "reset".
      sendReset = () => {
        seq++
        deliver({ v: 2, type: 'event', t: Date.now(), seq, src: 'sim', id: `mock-reset-${seq}`, kind: 'reset', info: {} } satisfies EventMsg)
      }
      setConnected(true)
      const id = setInterval(() => {
        const t = performance.now() - t0
        if (scenario === 'stall' && t > 1000) return clearInterval(id)
        // ?mock=demo: each new loop begins the way a demo does between judges, right after a reset.
        if (scenario === 'demo' && Math.floor(t / DEMO_MS) > loop) {
          loop = Math.floor(t / DEMO_MS)
          sendReset()
        }
        deliver(mockState(scenario, ++seq, t, router, start))
      }, 100)
    },
    send(msg: CmdMsg) {
      if (msg.cmd === 'router_moved' && typeof msg.args.spot === 'string') router = msg.args.spot
      if (msg.cmd === 'router_home') router = HOME_SPOT
      if (msg.cmd === 'reset') sendReset()
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

/** A trained model whose timings were never measured: the contract keeps them null then, even when trained. */
const MOCK_MODEL = { trained: true, ver: 'mock', train_s: null, ms_per_decision: null, windows: 0, train_sessions: [], training: null }

/** Before training (the waiting state): nothing to report. */
const UNTRAINED = { trained: false, ver: null, train_s: null, ms_per_decision: null, windows: 0, train_sessions: [], training: null }

/** The board's readings are measurements; the mock has none. */
const NO_BOARD = { cpu_temp_c: null, cpu_mhz: null, cpu_pct: null }

/** How much longer the router-to-receiver link gets when the router moves from S-home to `spot`, in metres. */
function spotDistanceChange(spot: string): number {
  const [rx, ry] = nodePosition('unoq', HOME_SPOT)
  const [hx, hy] = nodePosition(routerId(), HOME_SPOT)
  const [sx, sy] = nodePosition(routerId(), spot)
  return Number((Math.hypot(sx - rx, sy - ry) - Math.hypot(hx - rx, hy - ry)).toFixed(3))
}
