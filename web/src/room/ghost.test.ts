import { describe, expect, it } from 'vitest'
import type { Pred } from './contract'
import { ghostFloor, ghostSpots, turn } from './ghost'

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
