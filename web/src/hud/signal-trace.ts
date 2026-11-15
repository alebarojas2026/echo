import type { LinkState, StateMsg } from '../room/contract'
import { HOME_SPOT, LINK_IDS, ZONES, floorSize, nodePosition, parseLinkId, zoneAt } from '../room/frame'
import { hudLayout, type HudLayout } from './layout'

// The live signal trace: how far each side's radio links have dropped from their baseline over the last 10 s.
// Every point is a reading the board sent (state.links[].drop_db). The drawing moves between two readings so the
// line scrolls smoothly, but it never adds, smooths or fills in a value: a link with no fresh reading is a gap.

export const WINDOW_MS = 10_000
/** The line is drawn this far behind the clock, so the newest reading is always revealed between two real ones. */
export const DELAY_MS = 150
/** Two readings further apart than this are not joined: the feed paused, and the line breaks. */
export const GAP_MS = 450

export interface Side {
  zone: number
  name: string
  links: string[]
}

export interface Sample {
  t: number
  /** Per side: the deepest drop among its fresh links in dB, or null when none of them has a reading. */
  drop: (number | null)[]
  /** Per side: the board says a person is on this side. */
  present: boolean[]
}

export interface Point { age: number; drop: number; present: boolean }

/**
 * Which links cross which side of the floor, from the layout (radio/nodes.json as the room applied it).
 * A link counts for a side when at least 40% of its run over the floor lies in that side's zone. Links that
 * stay off the floor (along the desk) are left out. Sides with no link are left out too.
 *
 * A layout with one zone whose links say crosses_spot is one spot: a single row, named as the zone, made of the
 * Bluetooth lines that cross it. Nothing is worked out from positions there, and there are no sides.
 */
export function signalSides(layout: HudLayout = hudLayout): Side[] {
  if (layout.zones.length === 1 && layout.links.some((link) => typeof link.crosses_spot === 'boolean')) {
    const links = layout.links.filter((link) => link.crosses_spot === true && link.kind === 'ble').map((link) => link.id)
    return links.length ? [{ zone: layout.zones[0].id, name: layout.zones[0].name, links }] : []
  }
  const [fw, fh] = floorSize()
  const steps = 200
  const sides = ZONES.map((zone) => ({ zone: zone.id, name: zone.name, links: [] as string[] }))
  for (const id of LINK_IDS) {
    const parts = parseLinkId(id)
    if (!parts) continue
    const a = nodePosition(parts.tx, HOME_SPOT)
    const b = nodePosition(parts.rx, HOME_SPOT)
    const counts = new Map<number, number>()
    let inside = 0
    for (let i = 0; i <= steps; i++) {
      const x = a[0] + ((b[0] - a[0]) * i) / steps
      const y = a[1] + ((b[1] - a[1]) * i) / steps
      if (x <= 0 || x >= fw || y <= 0 || y >= fh) continue
      const zone = zoneAt(x, y)
      if (!zone) continue
      inside++
      counts.set(zone, (counts.get(zone) ?? 0) + 1)
    }
    const run = (inside / (steps + 1)) * Math.hypot(b[0] - a[0], b[1] - a[1])
    if (run < 0.15) continue
    for (const side of sides) if ((counts.get(side.zone) ?? 0) >= 0.4 * inside) side.links.push(id)
  }
  return sides.filter((side) => side.links.length)
}

/** The deepest drop among a side's fresh links, or null when none has a reading against a baseline. */
export function sideDrop(side: Side, links: LinkState[]): number | null {
  let deepest: number | null = null
  for (const link of links) {
    if (!side.links.includes(link.id) || link.status !== 'ok' || typeof link.drop_db !== 'number' || !Number.isFinite(link.drop_db)) continue
    if (deepest === null || link.drop_db > deepest) deepest = link.drop_db
  }
  return deepest
}

export type TraceStatus = 'ok' | 'no-data' | 'no-readings' | 'no-baseline'

/** Why there is, or is not, a trace to draw right now. */
export function traceStatus(state: StateMsg | null, stale: boolean, sides: Side[]): TraceStatus {
  if (!state || stale) return 'no-data'
  const mine = state.links.filter((link) => sides.some((side) => side.links.includes(link.id)))
  if (!mine.length) return 'no-readings'
  if (mine.every((link) => link.base_dbm == null && link.drop_db == null)) return 'no-baseline'
  return 'ok'
}

export const NOTES: Record<Exclude<TraceStatus, 'ok'>, string> = {
  'no-data': '',
  'no-readings': 'No radio readings yet.',
  'no-baseline': 'No baseline yet. The trace starts once the empty space is measured.',
}

/** The readings of the last 10 s, one sample per state message. */
export class SignalHistory {
  sides: Side[] = []
  samples: Sample[] = []
  private key = ''
  private last = ''

  /** Reads the sides again when the layout has changed (it loads after the page does). */
  refreshSides(layout: HudLayout = hudLayout) {
    const sides = signalSides(layout)
    const key = JSON.stringify(sides)
    if (key === this.key) return
    this.key = key
    this.sides = sides
    this.samples = []
  }

  push(state: StateMsg, t: number) {
    // One sample per message. The same message can be drawn more than once (a redraw, or a copy of it).
    const id = `${state.src}:${state.seq}:${state.t}`
    if (id === this.last) return
    this.last = id
    const person = state.pred?.present && state.pred.kind === 'person' ? state.pred : null
    this.samples.push({
      t,
      drop: this.sides.map((side) => sideDrop(side, state.links)),
      present: this.sides.map((side) => !!person && (person.zone === side.zone || person.zone_set.includes(side.zone))),
    })
    const oldest = t - WINDOW_MS - DELAY_MS - 2 * GAP_MS
    while (this.samples.length && this.samples[0].t < oldest) this.samples.shift()
  }
}

/**
 * The runs of joined readings for one side, as (age behind the drawing edge, drop). A run ends at a missing
 * reading or a pause in the feed. The newest run stops at the drawing edge: its last point lies on the straight
 * line between the two readings around the edge.
 */
export function traceRuns(samples: Sample[], side: number, now: number): Point[][] {
  const edge = now - DELAY_MS
  const runs: Point[][] = []
  let run: Point[] = []
  let prev: Sample | null = null
  const close = () => {
    if (run.length > 1) runs.push(run)
    run = []
  }
  for (const sample of samples) {
    const drop = sample.drop[side]
    if (drop === null) {
      close()
      prev = null
      continue
    }
    if (prev && sample.t - prev.t > GAP_MS) {
      close()
      prev = null
    }
    if (sample.t > edge) {
      const before = prev?.drop[side]
      if (prev && before != null) {
        const f = (edge - prev.t) / (sample.t - prev.t)
        run.push({ age: 0, drop: before + (drop - before) * f, present: sample.present[side] })
      }
      break
    }
    run.push({ age: edge - sample.t, drop, present: sample.present[side] })
    prev = sample
  }
  close()
  return runs
}

/** A change from the baseline as a judge reads it: a 6.8 dB drop is "−6.8 dB". */
export function formatDrop(drop: number): string {
  const change = -drop
  const text = Math.abs(change).toFixed(1)
  return `${text === '0.0' ? '' : change < 0 ? '−' : '+'}${text} dB`
}
