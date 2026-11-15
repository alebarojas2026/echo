import { describe, expect, it } from 'vitest'
import type { LinkState } from './contract'
import { HeardNodes, heardNow } from './heard'
import { mockState } from './mock'

const link = (id: string, rate: number): LinkState => ({ id, dbm: -60, base_dbm: -60, drop_db: 0, rate_hz: rate, expected_hz: 9.5, status: rate > 0 ? 'ok' : 'stale', why: 0 })

describe('which devices are heard', () => {
  it('counts both ends of every link with readings, and nothing for a silent link', () => {
    expect([...heardNow([link('east>unoq:ble', 9), link('west>pi5:ble', 0)])].sort()).toEqual(['east', 'unoq'])
    expect(heardNow([]).size).toBe(0) // before any readings, nothing is drawn
  })

  it('shows a device after 300 ms of readings, keeps it through a short gap, and lets go after 2.5 s', () => {
    const h = new HeardNodes()
    const ids = ['east', 'unoq']
    const on = [link('east>unoq:ble', 9)]
    expect(h.update(ids, on, 0).get('east')).toBe('never')
    expect(h.update(ids, on, 350).get('east')).toBe('heard')
    expect(h.update(ids, [], 1000).get('east')).toBe('heard') // one missed second never makes it blink
    expect(h.update(ids, [], 3600).get('east')).toBe('lost') // quiet for 2.6 s: faint, "not heard"
    expect(h.update(ids, on, 3700).get('east')).toBe('lost')
    expect(h.update(ids, on, 4100).get('east')).toBe('heard') // back
  })

  it('never draws a device just because the file lists it', () => {
    const h = new HeardNodes()
    expect(h.update(['pi5b'], [link('east>unoq:ble', 9)], 0).get('pi5b')).toBe('never')
    expect(h.update(['pi5b'], [link('east>unoq:ble', 9)], 5000).get('pi5b')).toBe('never')
  })
})

describe('?mock=power', () => {
  it('switches the East beacon off: its links go quiet, then blind after 3 s, then come back', () => {
    expect(heardNow(mockState('power', 1, 4000).links).has('east')).toBe(true)
    const quiet = mockState('power', 1, 7000)
    expect(heardNow(quiet.links).has('east')).toBe(false)
    expect(quiet.links.filter((l) => l.id.startsWith('east>')).every((l) => l.status === 'stale')).toBe(true)
    expect(quiet.pred).not.toBeNull()
    const blind = mockState('power', 1, 10000)
    expect(blind.health.status).toBe('blind')
    expect(blind.pred).toBeNull()
    expect(heardNow(mockState('power', 1, 13000).links).has('east')).toBe(true)
  })
})
