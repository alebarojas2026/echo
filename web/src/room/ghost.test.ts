import { describe, expect, it } from 'vitest'
import type { Pred } from './contract'
import { ghostSpots } from './ghost'

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
