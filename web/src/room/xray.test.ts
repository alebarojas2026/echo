import { describe, expect, it } from 'vitest'
import type { Xray } from './contract'
import { shadowCentre, upsample, xrayPeak } from './xray'

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

describe('upsampling and the shadow centre', () => {
  it('keeps the values at cell centres, never goes below 0, and fills in between', () => {
    const src = [0, 0, 0, 0, 8, 0, 0, 0, 0]
    const up = upsample(src, 3, 3, 4)
    expect(up).toHaveLength(144)
    expect(Math.min(...up)).toBeGreaterThanOrEqual(0)
    const peak = up.indexOf(Math.max(...up))
    const [px, py] = [peak % 12, Math.floor(peak / 12)]
    expect(Math.abs(px - 5.5)).toBeLessThanOrEqual(0.5) // the source centre cell spans texels 4-7
    expect(Math.abs(py - 5.5)).toBeLessThanOrEqual(0.5)
    expect(Math.max(...up)).toBeGreaterThan(6)
  })

  it('finds the centre of the strongest people cells, ignoring objects', () => {
    const x = grid(10, 10, { [7 * 10 + 2]: 5, [7 * 10 + 3]: 5 }, { 11: 9 })
    const c = shadowCentre(x)!
    expect(c[0]).toBeCloseTo(-0.2 + 3 * 0.24) // halfway between ix 2 and 3
    expect(c[1]).toBeCloseTo(-0.2 + 7.5 * 0.24)
    expect(shadowCentre(grid(4, 4, { 2: 0.5 }))).toBeNull() // under 1 dB is no shadow
    expect(shadowCentre(null)).toBeNull()
  })
})
