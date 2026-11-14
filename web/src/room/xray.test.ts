import { describe, expect, it } from 'vitest'
import type { Xray } from './contract'
import { xrayPeak } from './xray'

const grid = (w: number, h: number, moving: Record<number, number> = {}, still: Record<number, number> = {}): Xray => ({
  w, h, cell_m: 0.24, origin_m: [-0.2, -0.2], n_links: 6,
  moving_db: Array.from({ length: w * h }, (_, i) => moving[i] ?? 0),
  static_db: Array.from({ length: w * h }, (_, i) => still[i] ?? 0),
})

describe('xray peak', () => {
  it('reads cells row by row from the south-west (index = iy*w + ix)', () => {
    const p = xrayPeak(grid(10, 10, { [7 * 10 + 2]: 5 }))!
    expect(p.layer).toBe('moving')
    expect(p.db).toBe(5)
    expect(p.xy[0]).toBeCloseTo(-0.2 + 2.5 * 0.24) // ix = 2
    expect(p.xy[1]).toBeCloseTo(-0.2 + 7.5 * 0.24) // iy = 7, north half
  })

  it('works for any w x h and picks the stronger layer', () => {
    const p = xrayPeak(grid(7, 3, { 4: 2 }, { 20: 6 }))!
    expect(p.layer).toBe('static')
    expect(p.xy[0]).toBeCloseTo(-0.2 + 6.5 * 0.24)
    expect(p.xy[1]).toBeCloseTo(-0.2 + 2.5 * 0.24)
  })

  it('is null for an empty or flat image, and ignores negative cells', () => {
    expect(xrayPeak(grid(4, 4))).toBeNull()
    expect(xrayPeak(grid(4, 4, { 3: -4 }))).toBeNull()
    expect(xrayPeak(grid(0, 0))).toBeNull()
  })
})
