import { describe, expect, it } from 'vitest'
import type { Pred } from './contract'
import { turn } from './figure'
import { CROSS_MS, GONE_HOLD_MS, WALK_ON_M, crossing, ghostFloor, ghostSpots, holdsPose, objectTagAt, walkOnAlpha } from './ghost'

const pred = (over: Partial<Pred>): Pred => ({
  present: true, kind: 'person', zone: 2, zone_set: [2], probs: [0.02, 0.08, 0.81, 0.07, 0.02],
  motion: 'still', still_s: 0, why: [], ...over,
})

describe('ghost spots', () => {
  it('draws nothing while pred is null or nobody is there', () => {
    expect(ghostSpots(null)).toEqual([])
    expect(ghostSpots(pred({ present: false, kind: 'none', zone: 0, zone_set: [] }))).toEqual([])
    expect(ghostSpots(pred({ kind: 'object' }))).toEqual([])
  })

  it('puts one solid ghost in pred.zone', () => {
    expect(ghostSpots(pred({}))).toEqual([{ zone: 2, weight: 1 }])
    expect(ghostSpots(pred({ zone: 3, zone_set: [] }))).toEqual([{ zone: 3, weight: 1 }])
  })

  it('shows both zones when zone_set has two, the likelier one more solid', () => {
    const spots = ghostSpots(pred({ zone: 4, zone_set: [4, 3], probs: [0.05, 0, 0, 0.35, 0.55] }))
    expect(spots.map((s) => s.zone)).toEqual([4, 3])
    expect(spots[0].weight).toBeGreaterThan(spots[1].weight)
    expect(spots[1].weight).toBeGreaterThan(0)
  })
})

describe('ghost floor point', () => {
  it('stands on the shadow when it lies inside the zone tile', () => {
    expect(ghostFloor(2, [1.4, 1.62])).toEqual([1.4, 1.62])
  })

  it('stays 0.15 m inside its tile when the shadow is near the edge', () => {
    const [x, y] = ghostFloor(2, [1.03, 1.97])
    expect(x).toBeCloseTo(1.15)
    expect(y).toBeCloseTo(1.85)
  })

  it('stands in the zone centre with no shadow, or a shadow in another zone', () => {
    expect(ghostFloor(2, null)).toEqual([1.5, 1.5])
    expect(ghostFloor(2, [0.4, 0.4])).toEqual([1.5, 1.5])
  })
})

describe('figure heading', () => {
  it('turns the short way round', () => {
    expect(turn(0, Math.PI / 2)).toBeCloseTo(Math.PI / 2)
    expect(turn(Math.PI * 0.9, -Math.PI * 0.9)).toBeCloseTo(Math.PI * 0.2)
    expect(turn(-Math.PI * 0.9, Math.PI * 0.9)).toBeCloseTo(-Math.PI * 0.2)
  })
})

describe('object tags', () => {
  it('sit centred 0.3 m north of the object, or south when north would reach the north zone names', () => {
    expect(objectTagAt([1.0, 0.2])).toEqual([1.0, 0.5, 0.08]) // the tray by the router
    expect(objectTagAt([0.4, 1.25])[1]).toBeCloseTo(1.55)
    expect(objectTagAt([0.4, 1.6])[1]).toBeCloseTo(1.3)
  })
})

describe('a dropped reading', () => {
  it('does not make the figure leave: the pose holds for a few readings, then lets go', () => {
    expect(GONE_HOLD_MS).toBeGreaterThanOrEqual(300) // at ten states a second, three in a row may go missing
    expect(GONE_HOLD_MS).toBeLessThanOrEqual(500) // and someone who really leaves is gone within half a second
    expect(holdsPose(1000, 1100)).toBe(true)
    expect(holdsPose(1000, 1000 + GONE_HOLD_MS - 1)).toBe(true)
    expect(holdsPose(1000, 1000 + GONE_HOLD_MS)).toBe(false)
  })

  it('never holds a figure that was not there, or across a clock that ran backwards (live to replay)', () => {
    expect(holdsPose(null, 1000)).toBe(false)
    expect(holdsPose(5000, 1000)).toBe(false)
  })
})

describe('walking on, off and through the one spot', () => {
  it('fades in as the figure comes on and out as it goes, with no pop at either end', () => {
    expect(walkOnAlpha(0)).toBe(0) // at the side: not there yet
    expect(walkOnAlpha(1)).toBe(1) // on the spot
    expect(walkOnAlpha(0.6)).toBe(1) // fully there before it stops
    expect(walkOnAlpha(-0.2)).toBe(0)
    let last = 0
    for (let p = 0; p <= 1.0001; p += 0.05) {
      const a = walkOnAlpha(p)
      expect(a).toBeGreaterThanOrEqual(last) // never dips: a walk off that turns back fades straight back in
      expect(a - last).toBeLessThan(0.2)
      last = a
    }
    expect(WALK_ON_M).toBeGreaterThan(0.4)
    expect(WALK_ON_M).toBeLessThan(1.2)
  })

  it('crosses at an even pace, unseen at both ends and solid in the middle', () => {
    expect(crossing(0)).toEqual({ along: 0, alpha: 0 })
    expect(crossing(1)).toEqual({ along: 1, alpha: 0 })
    expect(crossing(0.5)).toEqual({ along: 0.5, alpha: 1 })
    expect(crossing(0.25).along).toBeCloseTo(0.25)
    expect(crossing(2)).toEqual({ along: 1, alpha: 0 })
    for (let t = 0.2; t <= 0.75; t += 0.05) expect(crossing(t).alpha).toBe(1)
    // A walking pace across, not a dash: two walk-on lengths in the crossing time.
    const mps = (2 * WALK_ON_M) / (CROSS_MS / 1000)
    expect(mps).toBeGreaterThan(1)
    expect(mps).toBeLessThan(2)
    expect(CROSS_MS).toBe(900)
  })
})
