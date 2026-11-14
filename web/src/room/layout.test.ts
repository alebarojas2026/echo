import { describe, expect, it } from 'vitest'
import nodesJson from '../../../radio/nodes.json'
import * as frame from './frame'

// applyLayout changes module state, so the cases run in order on one copy of frame.ts.
const real = structuredClone(nodesJson)

describe('layout from nodes.json', () => {
  it('refuses malformed files and changes nothing', () => {
    expect(frame.applyLayout(null)).toBe(false)
    expect(frame.applyLayout({ v: 1, nodes: [] })).toBe(false)
    expect(frame.applyLayout({ ...real, nodes: real.nodes.slice(1) })).toBe(false) // a node missing
    expect(frame.applyLayout({ ...real, frame: { size_m: [0] } })).toBe(false)
    expect(frame.SQUARE_M).toBe(2)
    expect(frame.spotName('S-W30')).toBe('30 cm W')
  })

  it('accepts the repo file as it is', () => {
    expect(frame.applyLayout(real)).toBe(true)
    expect(frame.SQUARE_M).toBe(2)
    expect(frame.nodePosition('unoq', 'S-home')).toEqual([1, 2, 1])
  })

  it('follows a 1.5 m square and gate-7 router spots without a rebuild', () => {
    const s = 0.75
    const small = {
      ...real,
      frame: { ...real.frame, size_m: [1.5, 1.5] },
      nodes: real.nodes.map((n: { xyz_m: number[] }) => ({ ...n, xyz_m: [n.xyz_m[0] * s, n.xyz_m[1] * s, 1.0] })),
      router_spots: [
        { id: 'S-home', xyz_m: [0.75, 0, 1] },
        { id: 'S-W20', xyz_m: [0.55, 0, 1] },
      ],
      zones: real.zones.map((z: { id: number; name: string }) => (z.id === 2 ? { ...z, name: 'Desk' } : z)),
    }
    expect(frame.applyLayout(small)).toBe(true)
    expect(frame.SQUARE_M).toBe(1.5)
    expect(frame.zoneAt(0.8, 0.8)).toBe(2) // the zone line moves to 0.75 m
    expect(frame.zoneCenter(4)).toEqual([1.125, 0.375])
    expect(frame.toScene([0.75, 0.75, 0])).toEqual([0, 0, 0])
    expect(Object.keys(frame.ROUTER_SPOTS)).toEqual(['S-home', 'S-W20'])
    expect(frame.nodePosition('pi5', 'S-W20')).toEqual([0.55, 0, 1])
    expect(frame.spotName('S-W20')).toBe('20 cm W')
    expect(frame.spotName('S-home')).toBe('home')
    expect(frame.ZONES.find((z) => z.id === 2)!.name).toBe('Desk')
  })
})
