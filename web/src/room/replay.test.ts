import { describe, expect, it } from 'vitest'
import { Replay, rowAlert, rowPred, secondKind, timeline, type HistoryRow, type ReplayFrame } from './replay'

const T0 = 1_763_200_000_000
const row = (s: number, over: Partial<HistoryRow> = {}): HistoryRow => ({
  t: T0 + s * 1000, present: true, zone: 1, zone_set: [1], motion: 'still', armed: false, alert: false, health: 'ok', tamper: [], ...over,
})

// A short recording as GET /history returns it: walking in Left, crossing to Right, a second the board did not
// save (3), a blind second (5: present null), then nobody.
const ROWS = [
  row(0, { motion: 'moving' }), row(1), row(2, { zone: 2, zone_set: [2, 1], motion: 'moving' }),
  row(4, { zone: 2, zone_set: [2], alert: true }), row(5, { present: null, zone: null, zone_set: [], motion: null, health: 'blind' }),
  row(6, { present: false, zone: 0, zone_set: [], motion: null, armed: true, tamper: ['east'] }),
]

describe('replay seconds', () => {
  it('keep every second in order, a missing one as no record, never filled in', () => {
    const seconds = timeline([...ROWS].reverse())
    expect(seconds.map((s) => s.t - T0)).toEqual([0, 1000, 2000, 3000, 4000, 5000, 6000])
    expect(seconds.map(secondKind)).toEqual(['record', 'record', 'record', 'none', 'record', 'unknown', 'record'])
    expect(timeline([])).toEqual([])
  })

  it('draw the person from a record, nobody when present is false, and nothing at all when the brain did not know', () => {
    expect(rowPred(ROWS[2])).toMatchObject({ present: true, kind: 'person', zone: 2, zone_set: [2, 1], motion: 'moving' })
    expect(rowPred(row(0, { zone_set: [] }))!.zone_set).toEqual([1])
    expect(rowPred(ROWS[5])).toMatchObject({ present: false, kind: 'none', zone: 0, zone_set: [], motion: null })
    expect(rowPred(ROWS[4])).toBeNull() // present null: never read as false
    expect(rowPred(null)).toBeNull()
  })

  it('tint the alert zone only while the recorded alert was on', () => {
    expect(rowAlert(ROWS[3])).toMatchObject({ state: 'check_on', zone: 2 })
    expect(rowAlert(ROWS[1])).toBeNull()
  })
})

describe('the replay player', () => {
  function player() {
    const frames: ReplayFrame[] = []
    const ends: string[] = []
    const r = new Replay((f) => frames.push(f), (why) => ends.push(why))
    return { r, frames, ends }
  }

  it('shows each second in turn at N x speed, then hands back to live by itself', () => {
    const { r, frames, ends } = player()
    r.play(ROWS, 8) // 7 seconds at 8x: 875 ms
    expect(r.playing).toBe(true)
    expect(frames.map((f) => f.index)).toEqual([0])
    for (let t = 0; t < 860; t += 16) r.step(16) // 864 ms: the seventh second, not yet the end
    expect(frames.map((f) => f.index)).toEqual([0, 1, 2, 3, 4, 5, 6])
    expect(frames[3].second.row).toBeNull() // the missing second is shown as no record
    expect(ends).toEqual([])
    r.step(16)
    expect(r.playing).toBe(false)
    expect(ends).toEqual(['end'])
  })

  it('hands back to live at once when asked, and only once', () => {
    const { r, ends } = player()
    r.play(ROWS, 4)
    r.step(100)
    r.stop('live')
    r.stop('live')
    expect(r.playing).toBe(false)
    expect(ends).toEqual(['live'])
    expect(r.step(16)).toBe(false)
  })

  it('runs its own clock at the replay speed, so the figure\'s holds keep up', () => {
    const { r, frames } = player()
    r.play(ROWS, 10)
    r.step(150) // 1.5 s of recording
    expect(frames.at(-1)!.clockMs).toBe(1500)
  })

  it('does nothing with no rows', () => {
    const { r, frames } = player()
    r.play([], 8)
    expect(r.playing).toBe(false)
    expect(frames).toEqual([])
  })
})
