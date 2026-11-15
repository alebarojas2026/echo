import { describe, expect, it } from 'vitest'
import type { Advice } from './contract'
import { adviceArrow, spotShown } from './spots'

const advice = (to_spot: string): Advice => ({
  id: 'a7', cause: 'obstruction', near: 'pi5', xy_m: [1, 0.2], link: 'pi5>unoq:wifi', to_spot, move_m: [-0.3, 0],
  dist_change_m: 0.02, text: 'x', before_dbm: null, after_dbm: null, why: [],
})

describe('advice arrow', () => {
  it('runs from S-home to advice.to_spot while advice is set', () => {
    expect(adviceArrow(advice('S-W30'), 'S-home')).toEqual({ from: 'S-home', to: 'S-W30', done: false })
    expect(adviceArrow(advice('S-E30'), 'S-home')?.to).toBe('S-E30')
  })

  it('is marked done once the router stands on the advised spot', () => {
    expect(adviceArrow(advice('S-W30'), 'S-W30')?.done).toBe(true)
  })

  it('is absent without advice, for an unknown spot, or when the advice is to stay home', () => {
    expect(adviceArrow(null, 'S-home')).toBeNull()
    expect(adviceArrow(advice('S-N99'), 'S-home')).toBeNull()
    expect(adviceArrow(advice('S-home'), 'S-home')).toBeNull()
  })
})

describe('spot rings', () => {
  it('show only while advice points somewhere, and then both ends of the arrow', () => {
    const shown = (router: string, a: Advice | null) =>
      ['S-home', 'S-W30', 'S-E30'].filter((id) => spotShown(id, adviceArrow(a, router)))
    expect(shown('S-home', null)).toEqual([])
    expect(shown('S-home', advice('S-W30'))).toEqual(['S-home', 'S-W30'])
    expect(shown('S-W30', advice('S-W30'))).toEqual(['S-home', 'S-W30'])
    expect(shown('S-W30', null)).toEqual([])
  })
})
