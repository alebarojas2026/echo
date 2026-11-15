import { describe, expect, it } from 'vitest'
import { WAVE_MS, WaveClock, alertLook, alertWordAt } from './alert'
import type { Alert } from './contract'
import { stillTimeline } from './mock'
import { FAULT, PERSON } from './palette'

const ci = (t: number) => ({ t, link: 'pi5>unoq:wifi' })

describe('wave check-in window', () => {
  it('shows a new check-in for 6 s from when the screen sees it', () => {
    const w = new WaveClock()
    expect(w.update(null, 0)).toBe(false)
    expect(w.update(ci(1000), 100)).toBe(true)
    expect(w.link).toBe('pi5>unoq:wifi')
    expect(w.update(ci(1000), 100 + WAVE_MS - 1)).toBe(true) // the same check-in keeps arriving
    expect(w.update(ci(1000), 100 + WAVE_MS)).toBe(false)
  })

  it('ignores the check-in already there when the screen starts, and restarts on a newer one', () => {
    const w = new WaveClock()
    expect(w.update(ci(500), 0)).toBe(false) // old news
    expect(w.update(ci(500), 50)).toBe(false)
    expect(w.update(ci(9000), 7000)).toBe(true)
    expect(w.update(ci(9100), 12000)).toBe(true) // a second wave restarts the 6 s
    expect(w.update(ci(9100), 17999)).toBe(true)
    expect(w.update(ci(9100), 18000)).toBe(false)
  })
})

describe('alert look', () => {
  const alert = (state: Alert['state'], zone: number | null = 4): Alert => ({ state, zone, still_s: 3, limit_s: 10 })

  it('marks a counting zone lightly in the person colour', () => {
    expect(alertLook(alert('counting'))).toEqual({ zone: 4, color: PERSON, fill: 0.15, width: 3, breathe: false })
  })

  it('marks a fired alert in red, wider, breathing', () => {
    expect(alertLook(alert('check_on'))).toEqual({ zone: 4, color: FAULT, fill: 0.3, width: 6, breathe: true })
  })

  it('marks nothing with no alert, no zone, or a zone that is not 1-4', () => {
    for (const a of [null, alert('none'), alert('counting', null), alert('check_on', 0)]) expect(alertLook(a).zone).toBeNull()
  })
})

describe('mock timelines', () => {
  const start = 1_700_000_000_000

  it('still: counts to 10 s, fires, and clears through a check-in at 14 s', () => {
    expect(stillTimeline('still', 4000, start).alert.state).toBe('counting')
    expect(stillTimeline('still', 11000, start).alert.state).toBe('check_on')
    expect(stillTimeline('still', 11000, start).checkin).toBeNull()
    const after = stillTimeline('still', 14500, start)
    expect(after.alert.state).toBe('counting')
    expect(after.checkin).toEqual({ t: start + 14000, link: 'pi5>unoq:wifi' })
  })

  it('checkin: counts for 5 s, then one check-in that keeps its t until the next one', () => {
    expect(stillTimeline('checkin', 2000, start).checkin).toBeNull()
    const a = stillTimeline('checkin', 6000, start)
    const b = stillTimeline('checkin', 14000, start)
    expect(a.alert.state).toBe('none')
    expect(a.checkin).toEqual(b.checkin)
    expect(stillTimeline('checkin', 21000, start).checkin!.t).toBe(start + 20000)
  })
})

describe('alert word', () => {
  it('sits just outside the square on the side of the alert zone, level with its name', () => {
    const [[x4, y4], side4] = alertWordAt(4)
    expect(x4).toBeGreaterThan(2)
    expect(y4).toBeLessThan(1)
    expect(side4).toBe('east')
    const [[x1, y1], side1] = alertWordAt(1)
    expect(x1).toBeLessThan(0)
    expect(y1).toBeGreaterThan(1)
    expect(side1).toBe('west')
  })
})
