import { describe, expect, it } from 'vitest'
import { FpsTally } from './fps'
import { viewOptions } from './view'

describe('fps meter', () => {
  it('skips the warm-up second, then keeps the running min and average', () => {
    const t = new FpsTally()
    expect(t.add(12)).toBeNull()
    expect(t.add(60)).toEqual({ now: 60, min: 60, avg: 60, seconds: 1 })
    expect(t.add(40)).toEqual({ now: 40, min: 40, avg: 50, seconds: 2 })
  })
})

describe('view options from the URL', () => {
  it('defaults to the setting measured on a Pi 5: antialiasing on, 3D at 0.85 scale', () => {
    expect(viewOptions(new URLSearchParams(''))).toEqual({ antialias: true, pixelRatio: 0.85 })
  })

  it('reads ?aa=0 and a sane ?dpr=', () => {
    expect(viewOptions(new URLSearchParams('aa=0&dpr=2'))).toEqual({ antialias: false, pixelRatio: 2 })
    expect(viewOptions(new URLSearchParams('aa=1')).antialias).toBe(true)
    expect(viewOptions(new URLSearchParams('dpr=0.75')).pixelRatio).toBe(0.75)
    expect(viewOptions(new URLSearchParams('dpr=nope')).pixelRatio).toBe(0.85)
    expect(viewOptions(new URLSearchParams('dpr=9')).pixelRatio).toBe(0.85)
  })
})
