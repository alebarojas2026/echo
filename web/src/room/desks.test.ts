import { beforeAll, describe, expect, it } from 'vitest'
import { defaultSpot, deskFit, deskName, modelPoint, nearestSpot, parseDesks, slideDesk, stepDesk, type HallDesks } from './desks'
import { applyLayout, toScene } from './frame'
import { DESK_LAYOUT } from './layouts.fixture'
import { placeScan } from './scan'

// A small hall in the file's own form: three rows of two blocks around one centre, rising a step every row.
// Not a real room's numbers.
const HALL: HallDesks = parseDesks({
  centre_m: [0, -10],
  desk_depth_m: 0.6,
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
