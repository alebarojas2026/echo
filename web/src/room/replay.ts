import type { Alert, Pred } from './contract'

// Replay (#537): the 3D room plays back what the board recorded (GET /history rows, one a second, contract #533)
// at N times speed, then hands back to live. While it plays, the figure, the zone tint and the alert tint come from
// the rows instead of the live feed; the devices and links stay live. A second with no row, or one where the brain
// did not know (present: null), greys the room under a notice, so it never reads as an empty room.
//
// Driving it from anywhere on the page (the HUD needs no import from web/src/room):
//   window.dispatchEvent(new CustomEvent('room:replay', { detail: { rows, speed: 8 } }))   start (speed > 0)
//   window.dispatchEvent(new CustomEvent('room:live'))                                      back to live now
// The room answers on window:
//   'room:replay-frame'  detail { t, index, count, kind: 'record' | 'unknown' | 'none' }   each replayed second
//   'room:replay-end'    detail { reason: 'end' | 'live' }                                 back to live
// and on the room element: data-replay="on" while it plays, data-replay-t = the second shown (epoch ms).

/** One row of GET /history, exactly as the board saves it once a second. */
export interface HistoryRow {
  t: number
  /** null: the brain did not know then (blind, no model). Never read as false. */
  present: boolean | null
  zone: number | null
  zone_set: number[]
  motion: 'moving' | 'still' | null
  armed: boolean
  alert: boolean
  health: 'ok' | 'degraded' | 'blind'
  tamper: string[]
}

/** A replayed second: its row, or null when nothing was saved for it. */
export interface Second {
  t: number
  row: HistoryRow | null
}

/** Every second from the first row to the last, in order; a second with no row is kept as null, never filled in. */
export function timeline(rows: readonly HistoryRow[]): Second[] {
  const sorted = [...rows].sort((a, b) => a.t - b.t)
  if (!sorted.length) return []
  const t0 = sorted[0].t
  const n = Math.round((sorted[sorted.length - 1].t - t0) / 1000) + 1
  const out: Second[] = Array.from({ length: n }, (_, i) => ({ t: t0 + i * 1000, row: null }))
  for (const r of sorted) out[Math.round((r.t - t0) / 1000)].row = r
  return out
}

/** What a second says: a record, a record where the brain did not know, or no record at all. */
export function secondKind(s: Second): 'record' | 'unknown' | 'none' {
  return !s.row ? 'none' : s.row.present === null ? 'unknown' : 'record'
}

/** The person as the room draws them for a recorded second; null when there is nothing to draw from. */
export function rowPred(row: HistoryRow | null): Pred | null {
  if (!row || row.present === null) return null
  const zone = row.present ? (row.zone ?? 0) : 0
  return {
    present: row.present && zone > 0,
    kind: row.present && zone > 0 ? 'person' : 'none',
    zone,
    zone_set: row.present ? (row.zone_set.length ? row.zone_set : zone ? [zone] : []) : [],
    probs: [],
    motion: row.present ? row.motion : null,
    still_s: 0,
    why: [],
  }
}

/** The alert tint for a recorded second: the fired alert in its zone, or none. */
export function rowAlert(row: HistoryRow | null): Alert | null {
  if (!row?.alert || !row.zone) return null
  return { state: 'check_on', zone: row.zone, still_s: 0, limit_s: null }
}

export interface ReplayFrame {
  second: Second
  index: number
  count: number
  /** The replay's own clock (ms), for the figure's holds: they run at the replay's speed. */
  clockMs: number
}

/** Steps through the seconds at `speed` x real time. The room calls step() every frame it draws. */
export class Replay {
  private seconds: Second[] = []
  private speed = 8
  private at = -1
  private clockMs = 0

  constructor(
    private readonly show: (frame: ReplayFrame) => void,
    private readonly backToLive: (reason: 'end' | 'live') => void,
  ) {}

  get playing(): boolean {
    return this.at >= 0
  }

  /** The second on screen and the replay clock now, while playing (for the figure, every frame). */
  get now(): { second: Second; clockMs: number } | null {
    return this.at >= 0 ? { second: this.seconds[this.at], clockMs: this.clockMs } : null
  }

  play(rows: readonly HistoryRow[], speed = 8) {
    this.seconds = timeline(rows)
    this.speed = speed > 0 ? speed : 8
    this.clockMs = 0
    this.at = this.seconds.length ? 0 : -1
    if (this.at === 0) this.emit()
  }

  stop(reason: 'end' | 'live' = 'live') {
    if (this.at < 0) return
    this.at = -1
    this.backToLive(reason)
  }

  /** Advances by dtMs of real time. Returns true while it is still playing (the room keeps drawing). */
  step(dtMs: number): boolean {
    if (this.at < 0) return false
    this.clockMs += dtMs * this.speed
    const next = Math.floor(this.clockMs / 1000)
    if (next >= this.seconds.length) {
      this.stop('end')
      return false
    }
    if (next !== this.at) {
      this.at = next
      this.emit()
    }
    return true
  }

  private emit() {
    this.show({ second: this.seconds[this.at], index: this.at, count: this.seconds.length, clockMs: this.clockMs })
  }
}
