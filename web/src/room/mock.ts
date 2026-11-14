import type { Advice, CmdMsg, LinkState, ObjectMark, Pred, StateMsg, Xray } from './contract'
import type { Transport } from './feed'
import { HOME_SPOT, LINK_IDS, nodePosition, parseLinkId, zoneAt } from './frame'

// Mock state messages (CONTRACTS.md v2 section 5) for building the screen without the board.
// src is "sim" so nothing here can pass for live, and measured numbers (train time, ms per decision,
// before/after dBm) stay null so the panels show "__".
//
// ?mock= tour (default) | still | object | blind | empty | stall
//   tour    someone walks a loop through the four zones, pausing in each
//   still   someone stays still in zone 4 and the no-movement alert counts up
//   object  an object sits next to the router, with advice to move the router
//   blind   the radio fails: health blind, pred null
//   empty   nobody in the room
//   stall   states for 1 s, then nothing (NO DATA)

export type MockScenario = 'tour' | 'still' | 'object' | 'blind' | 'empty' | 'stall'

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

export function mockState(scenario: MockScenario, seq: number, tMs: number, router = HOME_SPOT): StateMsg {
  const person = scenario === 'tour' ? tourAt(tMs) : scenario === 'still' ? { xy: [1.5, 0.5] as [number, number], moving: false } : null
  const object = scenario === 'object' ? OBJECT_XY : null
  const blind = scenario === 'blind'

  const links: LinkState[] = LINK_IDS.map((id, i) => {
    const near = (xy: [number, number] | null, db: number) => (xy ? db * Math.exp(-((distToLink(xy, id, router) / 0.2) ** 2)) : 0)
    const drop = near(person?.xy ?? null, 7) + near(object, 9) + 0.3 * Math.sin(tMs / 700 + i)
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
      kind: person ? 'person' : 'none',
      zone,
      zone_set: set,
      probs,
      motion: person?.moving ? 'moving' : 'still',
      still_s: scenario === 'still' ? (tMs / 1000) % 14 : 0,
      why: person ? top.slice(0, 2).map((l) => l.id) : [],
    }
  }

  const xray: Xray = {
    ...XRAY,
    moving_db: blob(person?.moving ? person.xy : null, 6),
    static_db: blob(object ?? (scenario === 'still' ? person!.xy : null), object ? 8 : 3),
    n_links: 6,
  }
  const objects: ObjectMark[] = object ? [{ xy_m: object, near: 'pi5', since_s: tMs / 1000, drop_db: 9 }] : []
  const advice: Advice | null =
    object && router === HOME_SPOT
      ? {
          id: 'a1', cause: 'obstruction', near: 'pi5', xy_m: object, link: 'pi5>unoq:wifi', to_spot: 'S-W30',
          move_m: [-0.3, 0], dist_change_m: null, before_dbm: null, after_dbm: null, why: ['pi5>unoq:wifi'],
          text: 'An object next to the router is blocking its link to the receiver. Move the router 30 cm west.',
        }
      : null
  const stillS = pred?.still_s ?? 0

  return {
    v: 2, type: 'state', t: Date.now(), seq, src: 'sim', cam: 'off', router, links,
    health: blind ? { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' } : { status: 'ok', blind: [], reason: null },
    pred, objects, xray,
    alert: scenario === 'still'
      ? { state: stillS >= 10 ? 'check_on' : 'counting', zone: 4, still_s: Number(stillS.toFixed(1)), limit_s: 10 }
      : { state: 'none', zone: null, still_s: null, limit_s: null },
    checkin: null, advice, narration: null, teacher: null,
    model: { trained: true, ver: 'mock', train_s: null, ms_per_decision: null, windows: null, train_sessions: [], training: null },
    board: null,
  }
}

/** A Transport that plays a scenario at 10 states a second and answers router commands. */
export function createMockSource(scenario: MockScenario): Transport {
  let router = HOME_SPOT
  return {
    start(deliver, setConnected) {
      const t0 = performance.now()
      let seq = 0
      setConnected(true)
      const id = setInterval(() => {
        const t = performance.now() - t0
        if (scenario === 'stall' && t > 1000) return clearInterval(id)
        deliver(mockState(scenario, ++seq, t, router))
      }, 100)
    },
    send(msg: CmdMsg) {
      if (msg.cmd === 'router_moved' && typeof msg.args.spot === 'string') router = msg.args.spot
      if (msg.cmd === 'router_home') router = HOME_SPOT
    },
  }
}
