import { afterAll, describe, expect, it } from 'vitest'
import * as frame from './frame'
import { DESK_LAYOUT, GATE_LAYOUT } from './layouts.fixture'
import { mockState, tourAt } from './mock'
import { deskAnchors } from './view'

// Zones along a strip (contract section 3): any number, side by side. One zone is the whole strip; neighbours
// meet halfway between their centre_m; with exactly two, frame.zone_split_x_m wins when the file gives it.

/** The gate's devices on a strip `width` wide with zones at these centres (x), named in order. */
function strip(width: number, centres: readonly number[], extra: Record<string, unknown> = {}) {
  const names = ['Left', 'Middle', 'Right', 'Far right']
  return {
    ...GATE_LAYOUT,
    frame: { ...GATE_LAYOUT.frame, size_m: [width + 0.05, 1.35], strip_m: [width, 0.6], ...extra },
    zones: centres.map((x, i) => ({ id: i + 1, name: centres.length === 1 ? 'At the desk' : names[i], centre_m: [x, 0.3], still_alert_s: 10 })),
  }
}

describe('zones along a strip', () => {
  afterAll(() => expect(frame.applyLayout(DESK_LAYOUT)).toBe(true))

  it('one zone is the whole strip', () => {
    expect(frame.applyLayout(strip(0.8, [0.4]))).toBe(true)
    expect(frame.ZONE_EDGES_X_M).toEqual([0, 0.8])
    expect(frame.ZONE_SPLIT_X_M).toBeNull()
    expect([0, 0.4, 0.8].map((x) => frame.zoneAt(x, 0.3))).toEqual([1, 1, 1])
    expect(frame.zoneRect(1)).toEqual([0, 0, 0.8, 0.6])
    expect(frame.zonesNamed()).toBe(true)
  })

  it('two zones meet at the split when the file gives one, and halfway between their centres when it does not', () => {
    expect(frame.applyLayout(strip(1.8, [0.45, 1.35], { zone_split_x_m: 1.1 }))).toBe(true)
    expect(frame.ZONE_EDGES_X_M).toEqual([0, 1.1, 1.8]) // the split wins over the centres' midpoint (0.9)
    expect(frame.ZONE_SPLIT_X_M).toBe(1.1)
    expect([0.2, 1.0, 1.1, 1.7].map((x) => frame.zoneAt(x, 0.3))).toEqual([1, 1, 2, 2])
    expect(frame.applyLayout(strip(1.8, [0.45, 1.35]))).toBe(true)
    expect(frame.ZONE_EDGES_X_M).toEqual([0, 0.9, 1.8])
    expect(frame.zoneRect(2)).toEqual([0.9, 0, 1.8, 0.6])
    expect(frame.zonesNamed()).toBe(true)
    // A split outside the strip is a wrong file, not one to guess around.
    expect(frame.applyLayout(strip(1.8, [0.45, 1.35], { zone_split_x_m: 2 }))).toBe(false)
  })

  it('three zones: left, middle and right, meeting halfway between neighbouring centres', () => {
    expect(frame.applyLayout(strip(1.8, [0.3, 0.9, 1.5]))).toBe(true)
    expect(frame.ZONE_EDGES_X_M.map((x) => Math.round(x * 100) / 100)).toEqual([0, 0.6, 1.2, 1.8])
    expect(frame.ZONE_SPLIT_X_M).toBeNull()
    expect([0.1, 0.59, 0.6, 1.19, 1.2, 1.8].map((x) => frame.zoneAt(x, 0.3))).toEqual([1, 1, 2, 2, 3, 3])
    expect(frame.zoneAt(0.9, 0.7)).toBe(0) // past the strip toward the desk
    expect(frame.zoneAt(-0.1, 0.3)).toBe(0)
    expect(frame.zoneRect(2)!.map((v) => Math.round(v * 100) / 100)).toEqual([0.6, 0, 1.2, 0.6])
    expect(frame.zoneCenter(2)).toEqual([0.9, 0.3])
    expect(frame.zoneRect(4)).toBeNull()
  })

  it('four zones, and centres that are not evenly spaced or listed in order', () => {
    expect(frame.applyLayout(strip(2.4, [0.3, 0.9, 1.5, 2.1]))).toBe(true)
    expect(frame.ZONE_EDGES_X_M.map((x) => Math.round(x * 100) / 100)).toEqual([0, 0.6, 1.2, 1.8, 2.4])
    expect([0.3, 0.9, 1.5, 2.1].map((x) => frame.zoneAt(x, 0.3))).toEqual([1, 2, 3, 4])
    // Zone 1 in the middle of the strip, zone 2 at its west end, zone 3 at its east end: the centres decide.
    const odd = strip(2.0, [1.0, 0.2, 1.6])
    expect(frame.applyLayout(odd)).toBe(true)
    expect(frame.ZONE_EDGES_X_M.map((x) => Math.round(x * 100) / 100)).toEqual([0, 0.6, 1.3, 2])
    expect([0.1, 1.0, 1.9].map((x) => frame.zoneAt(x, 0.3))).toEqual([2, 1, 3])
    expect(frame.zoneRect(1)!.map((v) => Math.round(v * 100) / 100)).toEqual([0.6, 0, 1.3, 0.6])
  })

  it('refuses three or more zones the file does not place: no centre, a centre off the strip, or two at one x', () => {
    const three = strip(1.8, [0.3, 0.9, 1.5])
    const without = { ...three, zones: three.zones.map((z, i) => (i === 1 ? { id: z.id, name: z.name } : z)) }
    expect(frame.applyLayout(without)).toBe(false)
    expect(frame.applyLayout(strip(1.8, [0.3, 0.9, 2.5]))).toBe(false)
    expect(frame.applyLayout(strip(1.8, [0.3, 0.9, 0.9]))).toBe(false)
    expect(frame.applyLayout({ ...three, zones: [] })).toBe(false)
  })

  it('writes no zone names on the floor above two zones, and keeps the no-movement word under the near corner', () => {
    expect(frame.applyLayout(strip(1.8, [0.3, 0.9, 1.5]))).toBe(true)
    expect(frame.zonesNamed()).toBe(false)
    for (const zone of [1, 2, 3]) expect(frame.alertWordAt(zone)[0]).toEqual([-0.04, -0.04, 0]) // never on the far desk
    expect(frame.applyLayout(strip(1.8, [0.45, 1.35]))).toBe(true)
    expect(frame.alertWordAt(2)[0][0]).toBeCloseTo(0.86) // two zones: each name under its own zone, as before
    expect(deskAnchors().length).toBeGreaterThan(8)
  })

  it('plays the simulated walk along the strip, through every zone in turn and back', () => {
    for (const centres of [[0.4], [0.45, 1.35], [0.3, 0.9, 1.5], [0.3, 0.9, 1.5, 2.1]]) {
      const width = centres.length === 1 ? 0.8 : centres.at(-1)! + centres[0]
      expect(frame.applyLayout(strip(width, centres))).toBe(true)
      const seen: number[] = []
      for (let t = 0; t < 120_000; t += 250) {
        const { xy } = tourAt(t)
        expect(xy[1]).toBeCloseTo(0.3) // straight along the strip, never out of it
        const zone = frame.zoneAt(xy[0], xy[1])
        expect(zone).toBeGreaterThan(0)
        if (seen.at(-1) !== zone) seen.push(zone)
      }
      expect(new Set(seen).size).toBe(centres.length)
      for (let i = 1; i < seen.length; i++) expect(Math.abs(seen[i] - seen[i - 1])).toBe(1) // neighbours only: no jump
      const s = mockState('still', 1, 5000)
      expect(s.pred!.probs).toHaveLength(centres.length + 1)
      expect(s.pred!.zone).toBe(centres.length)
    }
  })
})
