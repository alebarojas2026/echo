import { describe, expect, it } from 'vitest'
import { LINK_IDS } from './frame'
import { mockState, tourAt } from './mock'

describe('mock states', () => {
  it('keep to the contract shapes', () => {
    const s = mockState('tour', 7, 1234)
    expect(s).toMatchObject({ v: 2, type: 'state', seq: 7, src: 'sim' })
    expect(s.links.map((l) => l.id)).toEqual([...LINK_IDS])
    expect(s.xray!.moving_db).toHaveLength(s.xray!.w * s.xray!.h)
    expect(s.xray!.static_db).toHaveLength(s.xray!.w * s.xray!.h)
    expect(s.pred!.probs).toHaveLength(5)
    expect(s.model!.train_s).toBeNull() // measured numbers are never mocked
  })

  it('walk the tour through all four zones', () => {
    const zones = new Set<number>()
    for (let t = 0; t < 20000; t += 500) zones.add(mockState('tour', 1, t).pred!.zone)
    expect([...zones].sort()).toEqual([1, 2, 3, 4])
    expect(tourAt(4000).moving).toBe(false)
    expect(tourAt(1000).moving).toBe(true)
  })

  it('put the moving shadow where the person is', () => {
    const x = mockState('tour', 1, 1500).xray! // mid-walk
    const moving = x.moving_db
    const peak = moving.indexOf(Math.max(...moving))
    const [cx, cy] = [x.origin_m[0] + ((peak % x.w) + 0.5) * x.cell_m, x.origin_m[1] + (Math.floor(peak / x.w) + 0.5) * x.cell_m]
    const at = tourAt(1500).xy
    expect(Math.hypot(cx - at[0], cy - at[1])).toBeLessThan(x.cell_m)
  })

  it('keep a still person out of the object layer', () => {
    const x = mockState('still', 1, 3000).xray!
    expect(Math.max(...x.moving_db)).toBeGreaterThan(1)
    expect(Math.max(...x.static_db)).toBe(0)
    expect(Math.max(...mockState('object', 1, 0).xray!.static_db)).toBeGreaterThan(1)
  })

  it('drop pred when blind or when the router is off home', () => {
    const blind = mockState('blind', 1, 0)
    expect(blind.pred).toBeNull()
    expect(blind.health.status).toBe('blind')
    expect(blind.links.find((l) => l.status === 'blind')).toBeTruthy()
    expect(mockState('tour', 1, 0, 'S-W30').pred).toBeNull()
  })

  it('give advice for an object next to the router only while the router is home', () => {
    expect(mockState('object', 1, 0).advice?.to_spot).toBe('S-W30')
    expect(mockState('object', 1, 0, 'S-W30').advice).toBeNull()
  })
})
