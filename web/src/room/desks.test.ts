import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { PLACEMENT, defaultSpot, deskFit, deskName, loadDesks, modelPoint, nearestSpot, parseDesks, placementGuide, slideDesk, stepDesk, type Gap, type HallDesks } from './desks'
import { NODES, applyLayout, toScene } from './frame'
import { DESK_LAYOUT } from './layouts.fixture'
import { placeScan } from './scan'

// A small hall in the file's own form: three rows of two blocks around one centre, rising a step every row.
// Not a real room's numbers.
const HALL: HallDesks = parseDesks({
  centre_m: [0, -10],
  desk_depth_m: 0.6,
  desk_height_m: 0.74,
  desks: [0, 1, 2].flatMap((row) => [
    { row, wedge: 0, r_m: 20 + 1.5 * row, th0_deg: -14, th1_deg: -1, floor_m: 0.15 * (row + 1) },
    { row, wedge: 1, r_m: 20 + 1.5 * row, th0_deg: 1, th1_deg: 14, floor_m: 0.15 * (row + 1) },
  ]),
})!
const BOX = { min: [-15, 0, -1], max: [17, 6, 22] }
const at = (row: number, wedge: number, along = 0.5) => ({ desk: HALL.desks.find((d) => d.row === row && d.wedge === wedge)!, along })

beforeAll(() => {
  expect(applyLayout(DESK_LAYOUT)).toBe(true)
})

/** Where a point of the model lands in the scene under an alignment (the way scan.ts places it). */
function placed([x, z]: [number, number], fit: ReturnType<typeof deskFit>): [number, number] {
  const p = placeScan(BOX.min as [number, number, number], BOX.max as [number, number, number], fit)
  const gx = x + p.inner[0]
  const gz = z + p.inner[2]
  return [gx * Math.cos(p.yaw) + gz * Math.sin(p.yaw) + p.outer[0], -gx * Math.sin(p.yaw) + gz * Math.cos(p.yaw) + p.outer[2]]
}

describe('the hall\'s desks', () => {
  it('reads the file and refuses anything else', () => {
    expect(HALL.desks).toHaveLength(6)
    expect(parseDesks(null)).toBeNull()
    expect(parseDesks({ centre_m: [0, 0], desk_depth_m: 0.6, desks: [] })).toBeNull()
    expect(parseDesks({ centre_m: [0, 0], desk_depth_m: 0.6, desks: [{ row: 0, wedge: 0, r_m: 20, th0_deg: 5, th1_deg: 1, floor_m: 0 }] })).toBeNull()
  })

  it('names a desk the way people count: from the front and from 1', () => {
    expect(deskName(at(2, 0).desk)).toBe('Row 3, block 1')
  })

  it('defaults to the third row of the block nearest straight ahead', () => {
    const spot = defaultSpot(HALL)
    expect(spot.desk.row).toBe(2)
    expect(spot.along).toBe(0.5)
  })
})

describe('standing the strip at a desk', () => {
  it('puts the strip\'s desk edge on the desk\'s back edge, east along the desk, on its tier', () => {
    const spot = at(1, 1, 0.3)
    const fit = deskFit(HALL, spot, BOX, 12)
    expect(fit.floor_m).toBe(0.3)
    expect(fit.cut_m).toBe(12)
    // The desk's back edge at the spot, and a point 1 m further east along it, in the model:
    const th = ((1 + 13 * 0.3) * Math.PI) / 180
    const back = 21.5 + 0.3
    const edge: [number, number] = [back * Math.sin(th), -10 + back * Math.cos(th)]
    const east: [number, number] = [edge[0] + Math.cos(th), edge[1] - Math.sin(th)]
    const [mx, , mz] = toScene([0.8, 0.6, 0]) // the middle of the strip's desk edge
    const [ex, ez] = placed(edge, fit)
    expect(ex).toBeCloseTo(mx, 2)
    expect(ez).toBeCloseTo(mz, 2)
    const [fx, fz] = placed(east, fit)
    expect(fx - ex).toBeCloseTo(1, 2) // east is the scene's +x: the desk runs level across the screen
    expect(fz - ez).toBeCloseTo(0, 2)
  })

  it('finds the desk it stands at again from the alignment alone, and the nearest one after a nudge by hand', () => {
    const spot = at(2, 0, 0.4)
    const fit = deskFit(HALL, spot, BOX, 12)
    const [mx, , mz] = toScene([0.8, 0.6, 0])
    const found = nearestSpot(HALL, modelPoint([mx, mz], fit, BOX))
    expect(found.desk).toBe(spot.desk)
    expect(found.along).toBeCloseTo(0.4, 2)
    const nudged = { ...fit, offset_m: [fit.offset_m[0] + 0.3, fit.offset_m[1] - 0.4] as [number, number] }
    expect(nearestSpot(HALL, modelPoint([mx, mz], nudged, BOX)).desk).toBe(spot.desk)
  })

  it('steps to the next row and the next block, and stays when there is none that way', () => {
    expect(stepDesk(HALL, at(1, 0), 'north')!.desk).toBe(at(0, 0).desk)
    expect(stepDesk(HALL, at(1, 0), 'south')!.desk).toBe(at(2, 0).desk)
    expect(stepDesk(HALL, at(1, 0), 'east')!.desk).toBe(at(1, 1).desk)
    expect(stepDesk(HALL, at(1, 1), 'west')!.desk).toBe(at(1, 0).desk)
    expect(stepDesk(HALL, at(0, 0), 'north')).toBeNull()
    expect(stepDesk(HALL, at(1, 0), 'west')).toBeNull()
  })

  it('slides along a desk in metres and never hangs the strip past either end', () => {
    const spot = at(0, 1)
    const length = ((13 * Math.PI) / 180) * 20
    expect(slideDesk(spot, 0.5).along).toBeCloseTo(0.5 + 0.5 / length)
    expect(slideDesk(spot, 100).along).toBeCloseTo(1 - 0.8 / length)
    expect(slideDesk(spot, -100).along).toBeCloseTo(0.8 / length)
  })
})

describe('which side of our desk people stand on', () => {
  /** Where a layout point lands in the model under the alignment for a spot: undoes placed(). */
  const inModel = (layout: [number, number, number], fit: ReturnType<typeof deskFit>): [number, number] => {
    const [x, , z] = toScene(layout)
    return modelPoint([x, z], fit, BOX)
  }
  const polar = (r: number, thDeg: number): [number, number] => [r * Math.sin((thDeg * Math.PI) / 180), -10 + r * Math.cos((thDeg * Math.PI) / 180)]
  const near = (a: [number, number], b: [number, number]) => {
    expect(a[0]).toBeCloseTo(b[0], 1)
    expect(a[1]).toBeCloseTo(b[1], 1)
  }
  const spot = (gap: Gap, along = 0.5) => ({ ...at(1, 1, along), gap })

  it('behind: the strip is on the seating side, up the tiers from our desk, on our desk\u2019s tier', () => {
    const fit = deskFit(HALL, spot('behind'), BOX, 12)
    near(inModel([0.8, 0.6, 0], fit), polar(21.5 + 0.3, 7.5)) // our desk's back edge
    near(inModel([0.8, 0, 0], fit), polar(21.5 + 0.3 + 0.6, 7.5)) // the strip's far edge, further up
    expect(fit.floor_m).toBe(0.3)
  })

  it('front: the strip is toward the front of the hall, on the floor of the row below; the picture turns round', () => {
    const fit = deskFit(HALL, spot('front'), BOX, 12)
    near(inModel([0.8, 0.6, 0], fit), polar(21.5 - 0.3, 7.5)) // our desk's front edge
    near(inModel([0.8, 0, 0], fit), polar(21.5 - 0.3 - 0.6, 7.5)) // the strip's far edge, toward the front
    expect(fit.floor_m).toBe(0.15)
    const behind = deskFit(HALL, spot('behind'), BOX, 12)
    expect(Math.abs(Math.abs(fit.yaw_deg - behind.yaw_deg) - 180)).toBeLessThan(0.2)
    // In front of the first row there is no row below: the hall's front floor.
    expect(deskFit(HALL, { ...at(0, 1), gap: 'front' }, BOX, 12).floor_m).toBe(0)
  })

  it('end: the strip is past the desk\u2019s nearer end, in the aisle, with our desk\u2019s end as its north edge', () => {
    const east = deskFit(HALL, spot('end', 0.8), BOX, 12)
    near(inModel([0.8, 0.6, 0], east), polar(21.5, 14)) // the middle of the desk's east end
    const west = deskFit(HALL, spot('end', 0.2), BOX, 12)
    near(inModel([0.8, 0.6, 0], west), polar(21.5, 1))
    // The far edge is 0.6 m further along the row, away from the desk.
    const far = inModel([0.8, 0, 0], east)
    const end = polar(21.5, 14)
    expect(Math.hypot(far[0] - end[0], far[1] - end[1])).toBeCloseTo(0.6, 1)
    expect(Math.hypot(far[0], far[1] + 10)).toBeCloseTo(21.5, 0) // still on the row's arc, not up or down it
    expect(east.floor_m).toBe(0.3)
  })
})

describe('where the devices go', () => {
  const nodes = () => Object.values(NODES)
  const strip = [1.6, 0.6]
  const by = (places: ReturnType<typeof placementGuide>) => Object.fromEntries(places.map((p) => [p.id, p]))

  it('puts the board and the router together on our desk, at the edge facing the spot', () => {
    const g = by(placementGuide(HALL, { ...at(1, 1), gap: 'behind' }, nodes(), strip))
    expect(g.unoq.on).toBe('our desk')
    expect(g.pi5.on).toBe('our desk')
    expect(Math.abs(g.unoq.xyz[0] - g.pi5.xyz[0])).toBeCloseTo(PLACEMENT.nearApartM)
    expect((g.unoq.xyz[0] + g.pi5.xyz[0]) / 2).toBeCloseTo(0.8) // about the spot's middle
    expect(g.unoq.xyz[1]).toBeCloseTo(0.68) // 8 cm onto the desk from its edge
    expect(g.unoq.xyz[2]).toBeCloseTo(0.79) // on the desk top (0.74)
    expect(g.pi5.words).toBe('Pi A: on our desk, at the edge facing the spot, 4 cm left of the middle')
  })

  it('puts the other three across the gap on the facing desk\u2019s near edge, left to right as nodes.json has them', () => {
    const g = by(placementGuide(HALL, { ...at(1, 1), gap: 'behind' }, nodes(), strip))
    expect([g.west.on, g.pi5b.on, g.east.on]).toEqual(['facing desk', 'facing desk', 'facing desk'])
    expect([g.west.xyz[0], g.pi5b.xyz[0], g.east.xyz[0]]).toEqual([0.1, 0.8, 1.5])
    // Rows are 1.5 m apart and desks 0.6 m deep: the facing desk's edge is 0.9 m from ours, the device 8 cm onto it.
    expect(g.pi5b.xyz[1]).toBeCloseTo(0.6 - 0.9 - 0.08)
    // That desk stands on the next tier, 0.15 m up: its top is 0.89 m above the floor of the gap.
    expect(g.pi5b.xyz[2]).toBeCloseTo(0.15 + 0.74 + 0.05)
    expect(g.west.words).toBe('West beacon: on the desk across the gap, at its near edge, 70 cm left of the middle')
    expect(g.pi5b.words).toBe('Pi B: on the desk across the gap, at its near edge, in the middle')
  })

  it('stands them free where there is no desk across the gap: behind the last row, in front of the first, at a row\u2019s outer end', () => {
    for (const spot of [{ ...at(2, 1), gap: 'behind' as Gap }, { ...at(0, 1), gap: 'front' as Gap }, { ...at(1, 1, 0.9), gap: 'end' as Gap }]) {
      const g = by(placementGuide(HALL, spot, nodes(), strip))
      expect(g.east.on).toBe('stand')
      expect(g.east.xyz).toEqual([1.5, -0.4, 1])
      expect(g.east.words).toBe('East beacon: on a stand or chair back, 1 m across the gap and 1 m high, 70 cm right of the middle')
      expect(g.unoq.on).toBe('our desk')
    }
  })

  it('uses the neighbouring block\u2019s desk across a narrow aisle at the row end', () => {
    // Blocks 0 and 1 of a row are 2 degrees apart at 21.5 m: 0.75 m.
    const g = by(placementGuide(HALL, { ...at(1, 1, 0.1), gap: 'end' }, nodes(), strip))
    expect(g.pi5b.on).toBe('facing desk')
    expect(g.pi5b.xyz[1]).toBeCloseTo(0.6 - 0.75 - 0.08, 1)
  })

  it('swaps the two rows when the board is on the facing desk: the board and the router across, the rest on ours', () => {
    const g = by(placementGuide(HALL, { ...at(1, 1), gap: 'behind', boardAcross: true }, nodes(), strip))
    expect([g.unoq.on, g.pi5.on]).toEqual(['facing desk', 'facing desk'])
    expect(Math.abs(g.unoq.xyz[0] - g.pi5.xyz[0])).toBeCloseTo(PLACEMENT.nearApartM)
    expect([g.west.on, g.pi5b.on, g.east.on]).toEqual(['our desk', 'our desk', 'our desk'])
    expect([g.west.xyz[0], g.pi5b.xyz[0], g.east.xyz[0]]).toEqual([0.1, 0.8, 1.5])
    expect(g.pi5b.words).toBe('Pi B: on our desk, at the edge facing the spot, in the middle')
    expect(g.unoq.words).toBe('Board: on the desk across the gap, at its near edge, 4 cm right of the middle')
  })

  it('takes the spacing from the preset: a longer cable lets the board and the router sit apart', () => {
    const g = by(placementGuide(HALL, { ...at(1, 1), gap: 'behind' }, nodes(), strip, { ...PLACEMENT, nearApartM: 0.4 }))
    expect(Math.abs(g.unoq.xyz[0] - g.pi5.xyz[0])).toBeCloseTo(0.4)
    expect(g.pi5.words).toBe('Pi A: on our desk, at the edge facing the spot, 20 cm left of the middle')
  })
})

describe('loading the desk list', () => {
  const list = { centre_m: [0, 0], desk_depth_m: 0.45, desk_height_m: 0.75, desks: [{ row: 0, wedge: 0, r_m: 5, th0_deg: -10, th1_deg: 10, floor_m: 0 }] }
  afterEach(() => vi.unstubAllGlobals())

  it('uses the list the page was built with and never asks the network', async () => {
    const fetched = vi.fn()
    vi.stubGlobal('fetch', fetched)
    expect((await loadDesks('models/hall-desks.json', list))?.desks).toHaveLength(1)
    expect(fetched).not.toHaveBeenCalled()
    // The repo's own list is built in: the default argument finds it.
    expect((await loadDesks())?.desks.length).toBeGreaterThan(10)
    expect(fetched).not.toHaveBeenCalled()
  })

  it('asks again after a timeout when the page was built without the list, and stops at a plain "not there"', async () => {
    let calls = 0
    vi.stubGlobal('fetch', async () => {
      calls++
      if (calls < 3) throw new Error('timed out')
      return { ok: true, status: 200, json: async () => list }
    })
    expect((await loadDesks('models/hall-desks.json', null))?.desks).toHaveLength(1)
    expect(calls).toBe(3)
    calls = 0
    vi.stubGlobal('fetch', async () => (calls++, { ok: false, status: 404, json: async () => ({}) }))
    expect(await loadDesks('models/hall-desks.json', null)).toBeNull()
    expect(calls).toBe(1)
    calls = 0
    vi.stubGlobal('fetch', async () => {
      calls++
      throw new Error('down')
    })
    expect(await loadDesks('models/hall-desks.json', null)).toBeNull()
    expect(calls).toBe(3) // and then gives up: the hall stays where its alignment puts it
  })
})

describe('the guide on the gate layout', () => {
  // Three devices, one of them already across the spot: the file says how deep the gate is and how high each stands.
  const gate = (bz = 0.75, by = -0.2) => [
    { id: 'unoq', name: 'Board', xyz: [0.44, 0.8, 0.75] as [number, number, number], roles: ['receiver'] },
    { id: 'pi5', name: 'Pi A', xyz: [0.36, 0.8, 0.75] as [number, number, number], roles: ['router', 'beacon', 'receiver'] },
    { id: 'pi5b', name: 'Pi B', xyz: [0.4, by, bz] as [number, number, number], roles: ['beacon', 'receiver'] },
  ]
  // The fixture's rows are 0.9 m apart and its aisle 0.8 m wide: neither fits a 1 m gate and its table. The outer
  // end of a row (wedge 1's east end) has nothing beyond it.
  const guide = (gap: Gap, nodes = gate(), wedge = 1, along = 1) => placementGuide(HALL, { ...at(0, wedge, along), gap }, nodes, [0.8, 0.8])
  const place = (list: ReturnType<typeof placementGuide>, id: string) => list.find((p) => p.id === id)!

  it('at a row end stands Pi B on its own table, as far out and as high as the file has it', () => {
    const b = place(guide('end'), 'pi5b')
    expect(b.on).toBe('stand')
    expect(b.xyz).toEqual([0.4, -0.2, 0.75])
    expect(b.words).toBe('Pi B: on its own table, about 1 m straight out from the board')
    // Measured numbers drop in: a shorter gate and a lower table are kept, not overruled.
    const low = place(guide('end', gate(0.5, -0.05)), 'pi5b')
    expect(low.xyz).toEqual([0.4, -0.05, 0.5])
    expect(low.words).toBe('Pi B: on its own table, about 0.85 m straight out from the board')
  })

  it('between two rows puts Pi B on the desk across, never inside it, and says so', () => {
    const b = place(guide('behind'), 'pi5b')
    expect(b.on).toBe('facing desk')
    expect(b.words).toBe('Pi B: on the desk across from you, opposite the board')
    expect(b.xyz[1]).toBeGreaterThan(-0.2) // the row gap is narrower than the file's gate
    expect(b.xyz[1]).toBeLessThan(0.8)
    // The same at a row end whose aisle is too narrow for the table: the next block's desk takes it.
    expect(place(guide('end', gate(), 0, 1), 'pi5b').on).toBe('facing desk')
  })

  it('keeps the board and Pi A on our desk at its edge, 8 cm apart, at their own heights', () => {
    for (const gap of ['behind', 'front', 'end'] as const) {
      const [board, a] = [place(guide(gap), 'unoq'), place(guide(gap), 'pi5')]
      expect(board.on).toBe('our desk')
      expect(board.xyz[1]).toBe(0.8) // on the edge the layout names, so the drawn desk does not move when saved
      expect(a.xyz[1]).toBe(0.8)
      expect(board.xyz[0] - a.xyz[0]).toBeCloseTo(0.08)
      expect(board.xyz[2]).toBe(0.75)
    }
  })
})
