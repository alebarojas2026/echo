import { describe, expect, it } from 'vitest'
import { ghostTarget } from './ghost'
import { Glide3, GHOST_OMEGA, Held, springStep } from './motion'

describe('ghost spring', () => {
  it('reaches a 1 m step within 2% in about 650 ms and never overshoots', () => {
    let x = 0
    let v = 0
    let max = 0
    let settledAt = -1
    for (let t = 16; t <= 1500; t += 16) {
      ;[x, v] = springStep(x, v, 1, GHOST_OMEGA, 16)
      max = Math.max(max, x)
      if (settledAt < 0 && x > 0.98) settledAt = t
    }
    expect(max).toBeLessThanOrEqual(1)
    expect(settledAt).toBeGreaterThan(550)
    expect(settledAt).toBeLessThan(750)
  })

  it('stays stable on a slow 100 ms frame', () => {
    const [x] = springStep(0, 0, 1, GHOST_OMEGA, 100)
    expect(x).toBeGreaterThan(0)
    expect(x).toBeLessThan(1)
  })
})

describe('held values', () => {
  it('ignores a value that lasts one decision and takes one that holds', () => {
    const h = new Held('4', 200)
    expect(h.update('3', 0)).toBe('4')
    expect(h.update('4', 100)).toBe('4') // the 3 lasted one decision
    expect(h.update('3', 200)).toBe('4')
    expect(h.update('3', 300)).toBe('4')
    expect(h.update('3', 400)).toBe('3') // held 200 ms
  })

  it('can be quicker one way than the other', () => {
    const h = new Held(false, (on) => (on ? 300 : 800))
    h.update(true, 0)
    expect(h.update(true, 300)).toBe(true)
    h.update(false, 400)
    expect(h.update(false, 1100)).toBe(true)
    expect(h.update(false, 1200)).toBe(false)
  })
})

describe('ghost target', () => {
  it('stands in the zone centre when sure and toward the line when unsure', () => {
    expect(ghostTarget([4], [0, 0, 0, 0, 1], null)).toEqual([1.5, 0.5])
    const [x, y] = ghostTarget([3, 4], [0.04, 0, 0, 0.5, 0.46], null)!
    expect(x).toBeGreaterThan(0.9)
    expect(x).toBeLessThan(1.05)
    expect(y).toBeCloseTo(0.5)
  })
})

describe('router glide', () => {
  it('moves from the old spot to the new one in 600 ms', () => {
    const g = new Glide3([1, 0, 1])
    g.set([0.7, 0, 1])
    expect(g.now()[0]).toBe(1)
    g.step(300)
    expect(g.now()[0]).toBeCloseTo(0.85)
    g.step(300)
    expect(g.now()[0]).toBeCloseTo(0.7)
    expect(g.step(16)).toBe(false)
  })
})
