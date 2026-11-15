import { Box3, PerspectiveCamera, Vector3 } from 'three'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { beamLook, lineWidth, mainLine, overFloor } from './beams'
import * as frame from './frame'
import { DESK_LAYOUT, GATE_LAYOUT } from './layouts.fixture'
import { mockState, tourAt } from './mock'
import { clearBox } from './scan'
import { adviceArrow } from './spots'
import { onPad, onTable, padGeometry, standBase, tableGeometry } from './stage'
import { defaultSpot, deskFit, type HallDesks } from './desks'
import { hallShot, mixShot } from './fly'
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

  it('stands at the end of the desk by default, where the stair aisle has room for a gate a metre deep', () => {
    const hall: HallDesks = { centre_m: [0, 0], desk_depth_m: 0.45, desk_height_m: 0.75, desks: [{ row: 0, wedge: 0, r_m: 5, th0_deg: -10, th1_deg: 10, floor_m: 0 }] }
    expect(defaultSpot(hall).gap).toBe('end')
    // Of a row's ends, the one on the widest stair aisle: the far end's table has to clear the next block.
    const block = (wedge: number, th0: number, th1: number) => ({ row: 0, wedge, r_m: 26, th0_deg: th0, th1_deg: th1, floor_m: 0 })
    const rows: HallDesks = { ...hall, desks: [block(0, -30, -11), block(1, -8.4, 0), block(2, 2.7, 10), block(3, 12.4, 30)] }
    const aisle = (a: number, b: number) => (((rows.desks[b].th0_deg - rows.desks[a].th1_deg) * Math.PI) / 180) * 26
    expect(aisle(1, 2)).toBeGreaterThan(aisle(0, 1)) // 1.23 m against 1.18 m
    expect(aisle(1, 2)).toBeGreaterThan(aisle(2, 3)) // and 1.09 m
    expect(defaultSpot(rows)).toMatchObject({ desk: { wedge: 1 }, along: 1, gap: 'end' })
    // The hall is placed with its desk's edge under the layout's (y = 0.8), not under the spot's north edge.
    const fit = deskFit(hall, defaultSpot(hall), { min: [-9, 0, -9], max: [9, 3, 9] }, 12)
    const far = deskFit(hall, { ...defaultSpot(hall), gap: 'behind' }, { min: [-9, 0, -9], max: [9, 3, 9] }, 12)
    expect(fit.offset_m).not.toEqual(far.offset_m)
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
    expect(defaultSpot(hall).gap).toBeUndefined() // the desk layout stays behind its desk
    expect(frame.applyLayout(GATE_LAYOUT)).toBe(true)
  })

  it('shows the hall the right way up when the layout stands at a row end, and comes round to the desk', () => {
    const bounds = new Box3(new Vector3(-12, 0, -20), new Vector3(18, 6, 10))
    expect(hallShot(bounds, 12).azimDeg).toBeUndefined()
    expect(hallShot(bounds, 12, -7.3).azimDeg).toBeUndefined() // a desk on the curve of its row: as it was
    expect(hallShot(bounds, 12, 172.7).azimDeg).toBeUndefined() // in front of a desk: from the stage side, as it was
    const hall = hallShot(bounds, 12, -104.9) // the end of the default desk
    expect(hall.azimDeg).toBe(-104.9)
    // The camera stands where the turned hall's own south is: seen from there, the hall's front is at the top.
    const cam = new PerspectiveCamera(20, 1, 0.1, 500)
    fitCamera(cam, 1280, 1080, hall)
    const a = (-104.9 * Math.PI) / 180
    const south = new Vector3(Math.sin(a), 0, Math.cos(a))
    const flat = cam.position.clone().sub(hall.target).setY(0).normalize()
    expect(flat.dot(south)).toBeCloseTo(1)
    // The fly to the desk turns the short way, never past either end.
    const close = inSituShot(1280, 1080)
    for (const u of [0, 0.25, 0.5, 0.75, 1]) {
      const az = mixShot(hall, close, u).azimDeg!
      expect(az).toBeGreaterThanOrEqual(-104.9 - 1e-9)
      expect(az).toBeLessThanOrEqual(sideOnDeg() + 1e-9)
    }
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

  it('stands Pi B on a table of its own at whatever height the file gives, lower or higher than the desk', () => {
    const b = frame.NODES.pi5b.xyz
    expect(onTable(b, standBase(b))).toBe(true)
    expect(onTable(frame.NODES.unoq.xyz, standBase(frame.NODES.unoq.xyz))).toBe(false) // on our desk
    expect(onTable(b, [b[0], b[1], 0.7])).toBe(false) // already on something at that height (the next row's desk)
    for (const up of [0.45, 0.75, 1.05]) {
      expect(onTable([b[0], b[1], up], [b[0], b[1], 0])).toBe(true)
      const table = tableGeometry(up)
      table.computeBoundingBox()
      const box = table.boundingBox!
      expect(box.min.y).toBeCloseTo(0) // its legs stand on the ground
      expect(box.max.y).toBeCloseTo(up - 0.04) // its top is just under the device, wherever that is
      expect(box.min.z).toBeCloseTo(-0.05) // the device at the table's near edge, the table reaching away from the spot
      expect(box.max.z).toBeCloseTo(0.25) // a small table: it clears the next block across a 1.2 m aisle
    }
  })

  it('seats a device on the hall\u2019s furniture when the file\u2019s height would put it inside it', () => {
    // A hall with our desk's top at 0.745 m and the row behind a tier (0.156 m) higher, its desk from y = -0.195.
    const under = (_x: number, y: number, top: number) => {
      const tops = y >= 0.79 ? [0, 0.745] : y <= -0.195 ? [0.156, 0.901] : [0]
      const below = tops.filter((h) => h <= top)
      return below.length ? Math.max(...below) : null
    }
    const b = frame.NODES.pi5b.xyz
    expect(frame.seated(b)).toEqual(b) // no model: where the file has it
    frame.setSurface(under)
    expect(frame.seated(b)).toEqual([0.4, -0.2, 0.941]) // on the row behind's desk, a step above the board
    expect(frame.nodePosition('pi5b', null)[2]).toBeGreaterThan(frame.nodePosition('unoq', null)[2] + 0.1)
    expect(frame.nodePosition('unoq', null)[2]).toBeCloseTo(0.785) // on our desk's top, not 3 cm into it
    expect(frame.seated([0.4, 0.3, 0.75])).toEqual([0.4, 0.3, 0.75]) // over open floor: nothing to sit on
    // Seated, it needs no table of its own; the desk it sits on is see-through there, so a piece of its top is drawn.
    const at = frame.nodePosition('pi5b', null)
    expect(onTable(at, [at[0], at[1], 0.901])).toBe(false)
    expect(onPad(at, [at[0], at[1], 0.901], true)).toBe(true)
    expect(onPad(at, standBase(at), false)).toBe(false) // no model: the table, as before
    const board = frame.nodePosition('unoq', null)
    expect(onPad(board, [board[0], board[1], 0.745], true)).toBe(false) // our own desk is drawn solid
    padGeometry().computeBoundingBox()
    frame.setSurface(null)
    expect(frame.nodePosition('pi5b', null)).toEqual(b)
  })

  it('keeps the furniture a device across the spot stands on: the seats go, the desk behind stays', () => {
    const box = clearBox()
    const z = (y: number) => frame.toScene([0, y, 0])[2]
    expect(box.max.z).toBeCloseTo(z(-0.12)) // 8 cm short of Pi B at y = -0.2
    expect(box.containsPoint(new Vector3(frame.toScene([0.4, 0.3, 0.5])[0], 0.5, z(0.3)))).toBe(true) // a seat in the spot
    expect(box.containsPoint(new Vector3(frame.toScene([0.4, -0.2, 0.9])[0], 0.9, z(-0.2)))).toBe(false) // the desk's front edge
  })

  it('stands between the second row and the third by default, on the block nearest straight ahead', () => {
    const block = (row: number, wedge: number, th0: number, th1: number) => ({ row, wedge, r_m: 23 + 1.6 * row, th0_deg: th0, th1_deg: th1, floor_m: 0.156 * Math.ceil(row / 2 + 0.5) })
    const hall: HallDesks = {
      centre_m: [0, 0], desk_depth_m: 0.6, desk_height_m: 0.745,
      desks: [block(0, 1, -15, -3), block(0, 2, 3, 15), block(1, 0, -21, -19), block(1, 2, 3, 15), block(1, 3, 18, 31), block(2, 1, -16, -3), block(2, 2, 0, 15), block(3, 2, 0, 15)],
    }
    expect(defaultSpot(hall)).toMatchObject({ desk: { row: 1, wedge: 2 }, along: 0.5, gap: 'behind' })
    // A block with no desk of the next row behind its middle is passed over.
    const gap: HallDesks = { ...hall, desks: hall.desks.filter((d) => !(d.row === 2 && d.wedge === 2)) }
    expect(defaultSpot(gap).gap).toBe('end') // no pair of rows here: a row end, as before
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
    expect(defaultSpot(hall)).toMatchObject({ desk: { row: 2 }, along: 0.5 }) // the desk layout: the third row, behind its desk
    expect(defaultSpot(hall).gap).toBeUndefined()
    expect(frame.applyLayout(GATE_LAYOUT)).toBe(true)
  })

  it('draws the Wi-Fi line across the gap boldest, at rest and when it explains the prediction', () => {
    expect(frame.LINK_IDS.filter(mainLine)).toEqual(['pi5>pi5b:wifi'])
    expect(mainLine('pi5>unoq:wifi')).toBe(false) // 8 cm along the desk: crosses nothing
    expect(mainLine('pi5b>unoq:ble')).toBe(false) // crosses the spot, but Bluetooth: the second opinion
    const none = new Set<string>()
    const row = { id: 'pi5>pi5b:wifi', dbm: -60, base_dbm: -42, drop_db: 18, rate_hz: 25, expected_hz: 25, status: 'ok', why: 1 }
    const rest = beamLook(row, false, none)
    const lit = beamLook(row, true, none)
    expect(lineWidth(rest, true)).toBeGreaterThan(lineWidth(rest, false))
    expect(lineWidth(lit, true)).toBeGreaterThan(lineWidth(lit, false))
    expect(lineWidth(lit, true)).toBeGreaterThan(lineWidth(rest, true))
  })

  it('never tells anyone to move the router: it is cabled to the hub on this layout', () => {
    const advice = { to_spot: 'S-W30', move_m: [-0.3, 0], dist_change_m: 0, why: ['pi5>unoq:wifi'], before_dbm: -66, after_dbm: null }
    expect(adviceArrow(advice as never, 'S-home')).toBeNull()
    expect(adviceArrow(advice as never, 'S-W30')).toBeNull()
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
    expect(onTable(east, standBase(east))).toBe(false)
    expect(frame.LINK_IDS.some(mainLine)).toBe(false) // a file that marks no link has no main line
    const advice = { to_spot: 'S-W30', move_m: [-0.3, 0], dist_change_m: 0, why: ['pi5>unoq:wifi'], before_dbm: -66, after_dbm: null }
    expect(adviceArrow(advice as never, 'S-home')).toEqual({ from: 'S-home', to: 'S-W30', done: false }) // the desk's router still moves
    // Two zones with no split meet halfway between their centres (zones.test.ts has the rest of that rule).
    expect(frame.applyLayout({ ...DESK_LAYOUT, frame: { ...DESK_LAYOUT.frame, zone_split_x_m: undefined } })).toBe(true)
    expect(frame.ZONE_SPLIT_X_M).toBeCloseTo(0.8)
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
  })
})
