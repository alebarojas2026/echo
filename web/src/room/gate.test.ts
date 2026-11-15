import { PerspectiveCamera } from 'three'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { beamLook, overFloor } from './beams'
import * as frame from './frame'
import { DESK_LAYOUT, GATE_LAYOUT } from './layouts.fixture'
import { mockState, tourAt } from './mock'
import { clearBox } from './scan'
import { chairGeometry, onChair, standBase } from './stage'
import { defaultSpot, deskFit, type HallDesks } from './desks'
import { mixShot } from './fly'
import { xrayGeometry } from './xray'
import { deskAnchors, deskShot, fitCamera, inSituShot, sideOnDeg } from './view'

// The gate: three devices, six links, one spot. Everything the room draws comes from the file, and the desk
// layout (five devices, two zones) still reads as it did.
describe('the gate layout', () => {
  beforeAll(() => expect(frame.applyLayout(GATE_LAYOUT)).toBe(true))
  afterAll(() => expect(frame.applyLayout(DESK_LAYOUT)).toBe(true))

  it('is one spot: one zone over the whole strip, no split, named by the file alone', () => {
    expect(frame.STRIP_M).toEqual([0.8, 0.6])
    expect(frame.ZONE_SPLIT_X_M).toBeNull()
    expect(frame.ZONES.map((z) => z.id)).toEqual([1])
    expect(frame.zoneRect(1)).toEqual([0, 0, 0.8, 0.6])
    expect(frame.zoneAt(0.1, 0.1)).toBe(1)
    expect(frame.zoneAt(0.7, 0.5)).toBe(1)
    expect(frame.zoneAt(0.4, 0.7)).toBe(0) // between the spot and the desk
    expect(frame.zoneAt(0.4, -0.2)).toBe(0) // where Pi B's chair is
    expect(frame.zoneCenter(1)).toEqual([0.4, 0.3])
    expect(frame.zoneWords(1)).toBe('At the desk') // no "1": there is nothing to count
  })

  it('has three devices and six links, and none of the desk layout is left over', () => {
    expect(Object.keys(frame.NODES).sort()).toEqual(['pi5', 'pi5b', 'unoq'])
    expect(frame.LINK_IDS).toHaveLength(6)
    expect(frame.routerId()).toBe('pi5')
  })

  it('puts the desk where the devices stand, past the spot, by the file or from the devices', () => {
    expect(frame.deskEdge()).toBe(0.8)
    expect(standBase([0.44, 0.8, 0.75])[2]).toBeGreaterThan(0.5) // on the desk
    expect(standBase([0.4, 0.7, 0.75])[2]).toBe(0) // the floor between the spot and the desk
    expect(frame.applyLayout({ ...GATE_LAYOUT, frame: { ...GATE_LAYOUT.frame, desk_edge_y_m: 0.7 } })).toBe(true)
    expect(frame.deskEdge()).toBe(0.7)
    expect(frame.applyLayout({ ...GATE_LAYOUT, frame: { ...GATE_LAYOUT.frame, desk_edge_y_m: 0.2 } })).toBe(true)
    expect(frame.deskEdge()).toBe(0.8) // a desk edge inside the spot is not believed
    expect(frame.applyLayout(GATE_LAYOUT)).toBe(true)
    // The hall's chairs are kept out of everything a person can stand in, right up to the desk.
    expect(clearBox().min.z).toBeCloseTo(frame.toScene([0, 0.79, 0])[2])
  })

  it('lays the X-ray on the spot and on the desk top, and leaves the floor between them bare', () => {
    const g = xrayGeometry([-0.2, -0.2], [1.25, 1.75])
    const pos = g.getAttribute('position')
    const rows = new Map<number, number[]>() // height -> the scene z of its corners
    for (let i = 0; i < pos.count; i++) rows.set(Math.round(pos.getY(i) * 100), [...(rows.get(Math.round(pos.getY(i) * 100)) ?? []), pos.getZ(i)])
    const [floor, desk] = [...rows.keys()].sort((a, b) => a - b)
    expect(desk).toBeGreaterThan(70)
    const z = (y: number) => frame.toScene([0, y, 0])[2]
    expect(Math.min(...rows.get(floor)!)).toBeCloseTo(z(0.6)) // the floor part ends at the spot's north edge
    expect(Math.max(...rows.get(desk)!)).toBeCloseTo(z(0.8)) // the desk part starts at the desk's edge
  })

  it('stands at the desk's end by default, where the stair aisle has room for a gate a metre deep', () => {
    const hall: HallDesks = { centre_m: [0, 0], desk_depth_m: 0.45, desk_height_m: 0.75, desks: [{ row: 0, wedge: 0, r_m: 5, th0_deg: -10, th1_deg: 10, floor_m: 0 }] }
    expect(defaultSpot(hall).gap).toBe('end')
    // The hall is placed with its desk's edge under the layout's (y = 0.8), not under the spot's north edge.
    const fit = deskFit(hall, defaultSpot(hall), { min: [-9, 0, -9], max: [9, 3, 9] }, 12)
    const far = deskFit(hall, { ...defaultSpot(hall), gap: 'behind' }, { min: [-9, 0, -9], max: [9, 3, 9] }, 12)
    expect(fit.offset_m).not.toEqual(far.offset_m)
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
    expect(defaultSpot(hall).gap).toBeUndefined() // the desk layout stays behind its desk
    expect(frame.applyLayout(GATE_LAYOUT)).toBe(true)
  })

  it('draws the links that cross the spot in full and the two along the desk faint, by the file', () => {
    const none = new Set<string>()
    const row = (id: string) => ({ id, dbm: -60, base_dbm: -60, drop_db: 0, rate_hz: 4, expected_hz: 4, status: 'ok', why: 0 })
    for (const id of frame.LINK_IDS) {
      const crosses = id.includes('pi5b')
      expect(frame.LINK_CROSSES[id]).toBe(crosses)
      const { tx, rx } = frame.parseLinkId(id)!
      expect(overFloor(frame.NODES[tx].xyz, frame.NODES[rx].xyz)).toBe(crosses) // and the geometry agrees
      expect(beamLook(row(id), false, none, frame.LINK_CROSSES[id]).opacity).toBeCloseTo(crosses ? 1 : 0.3)
    }
  })

  it('is seen from one side, with every name on its device\'s far side from the person', () => {
    expect(frame.deviceAcross()).toBe(true)
    expect(sideOnDeg()).toBeLessThan(-30) // from the south-west: Pi B, the person and the desk read apart
    expect(frame.nodeLabelSide('pi5')).toBe('left')
    expect(frame.nodeLabelSide('unoq')).toBe('above-left')
    expect(frame.nodeLabelSide('pi5b')).toBe('right')
    const [at, reads] = frame.alertWordAt(1)
    expect(reads).toBe('south')
    expect(at[0]).toBeLessThan(0) // under the spot's near corner, not under its middle where Pi B's chair is
    expect(at[1]).toBeLessThan(0)
    // The camera's turn is part of the shot, and the fly carries it: the hall is seen from due south.
    expect(deskShot(1280, 1080).azimDeg).toBe(sideOnDeg())
    expect(inSituShot(1280, 1080).azimDeg).toBe(sideOnDeg())
    const half = mixShot({ ...inSituShot(1280, 1080), azimDeg: 0 }, inSituShot(1280, 1080), 0.5)
    expect(half.azimDeg).toBeCloseTo(sideOnDeg() / 2)
  })

  it('stands Pi B on a chair with a box that raises it to desk height, and nothing else', () => {
    const b = frame.NODES.pi5b.xyz
    expect(onChair(b, standBase(b))).toBe(true)
    expect(onChair(frame.NODES.unoq.xyz, standBase(frame.NODES.unoq.xyz))).toBe(false)
    expect(onChair(b, [b[0], b[1], 0.7])).toBe(false) // already on something at that height (the next row's desk)
    const chair = chairGeometry(0.75)
    chair.computeBoundingBox()
    expect(chair.boundingBox!.min.y).toBeCloseTo(0)
    expect(chair.boundingBox!.max.y).toBeCloseTo(0.85) // the chair's back
    expect(chair.boundingBox!.max.x - chair.boundingBox!.min.x).toBeCloseTo(0.42)
  })

  it('frames the spot, the three devices and the one name, all on the canvas', () => {
    for (const [w, h] of [[1280, 1080], [800, 900]]) {
      const cam = new PerspectiveCamera(20, 1, 0.1, 100)
      fitCamera(cam, w, h, deskShot(w, h))
      for (const a of deskAnchors(undefined, w)) {
        const p = a.at.clone().project(cam)
        expect(Math.abs(p.x)).toBeLessThanOrEqual(1)
        expect(Math.abs(p.y)).toBeLessThanOrEqual(1)
      }
    }
  })

  it('plays the simulated scenes on one spot: the person stays inside it and is found there', () => {
    for (let t = 0; t < 40_000; t += 700) {
      const { xy } = tourAt(t)
      expect(frame.zoneAt(xy[0], xy[1])).toBe(1)
    }
    for (const scenario of ['tour', 'still', 'between', 'checkin', 'object', 'demo', 'empty'] as const) {
      const s = mockState(scenario, 1, 5000)
      expect(s.links).toHaveLength(6)
      if (s.pred?.present) expect(s.pred.zone).toBe(1)
      expect(s.pred?.probs ?? [0, 0]).toHaveLength(2) // [empty, the one zone]
    }
  })
})

describe('the desk layout, after the gate', () => {
  it('still has two zones with a line between them, numbered names, and posts for its beacons', () => {
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
    expect(frame.ZONE_SPLIT_X_M).toBe(0.8)
    expect(frame.zoneWords(1)).toBe('1 Left')
    expect(frame.zoneWords(2)).toBe('2 Right')
    expect(frame.deskEdge()).toBe(0.6)
    expect(frame.LINK_CROSSES).toEqual({})
    expect(frame.deviceAcross()).toBe(false)
    expect(sideOnDeg()).toBe(0) // seen from due south, north up, as before
    expect(frame.nodeLabelSide('pi5')).toBe('above')
    expect(frame.alertWordAt(1)[0]).toEqual([0.4, -0.06, 0])
    const east = frame.NODES.east.xyz
    expect(onChair(east, standBase(east))).toBe(false)
    // Two zones on a strip still need their split; a single zone does not.
    expect(frame.applyLayout({ ...DESK_LAYOUT, frame: { ...DESK_LAYOUT.frame, zone_split_x_m: undefined } })).toBe(false)
    expect(frame.STRIP_M).toEqual([1.6, 0.6])
  })
})
