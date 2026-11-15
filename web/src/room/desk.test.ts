import { PerspectiveCamera, Vector3 } from 'three'
import { beforeAll, describe, expect, it } from 'vitest'
import { laneShifts, overFloor } from './beams'
import { demoScene } from './demo'
import { objectTagAt } from './ghost'
import { buildState, mockState } from './mock'
import { FIGURE_HEIGHT_M } from './figure'
import { LINK_IDS, NODES, SIZE_M, alertWordAt, applyLayout, toScene, type Vec3 } from './frame'
import { DESK_LAYOUT } from './layouts.fixture'
import { DESK_TOP_M, standBase } from './stage'
import { FOV_DEG, fitCamera, roomShot } from './view'
import { xrayGeometry } from './xray'

// The whole room on the desk layout of the contract PR (#415): this file applies it once; every other test file
// keeps the built-in square.
beforeAll(() => {
  expect(applyLayout(DESK_LAYOUT)).toBe(true)
})

describe('mocks on the desk layout', () => {
  it('send one prob per zone plus empty, all twelve links and the 16 x 12 X-ray', () => {
    const s = mockState('tour', 1, 1000)
    expect(s.pred!.probs).toHaveLength(3)
    expect(s.links.map((l) => l.id)).toEqual(LINK_IDS)
    expect(s.xray).toMatchObject({ w: 16, h: 12, cell_m: 0.125, n_links: 12 })
    expect(s.xray!.moving_db).toHaveLength(16 * 12)
  })

  it('walk Left and Right, stand still in Right, and stand between them', () => {
    const zones = new Set<number>()
    for (let t = 0; t < 20000; t += 500) zones.add(mockState('tour', 1, t).pred!.zone)
    expect([...zones].sort()).toEqual([1, 2])
    expect(mockState('still', 1, 12000).alert).toMatchObject({ state: 'check_on', zone: 2 })
    expect(mockState('between', 1, 0).pred!.zone_set).toEqual([2, 1])
  })

  it('put the tray on the desk as an object, never a person', () => {
    const s = mockState('object', 1, 0)
    expect(s.objects[0].xy_m).toEqual([0.86, 1.0])
    expect(s.pred).toMatchObject({ present: false, kind: 'object', zone: 0, zone_set: [] })
  })

  it('play the demo in the strip: into Right, still, over to Left, out', () => {
    const at = (s: number) => buildState(1, s * 1000, demoScene(s * 1000, 0))
    expect(at(6).pred).toMatchObject({ present: true, zone: 2, motion: 'moving' })
    expect(at(20).alert).toMatchObject({ state: 'check_on', zone: 2 })
    expect(at(43).pred).toMatchObject({ present: true, zone: 1 })
    expect(at(46.9).pred!.present).toBe(false) // stepped out of the strip
    expect(at(50).objects).toHaveLength(1)
  })
})

describe('the room drawn on the desk layout', () => {
  const W = 1280
  const H = 1080
  const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
  const px = (p: Vec3) => {
    const v = new Vector3(...toScene(p)).project(cam)
    return [((v.x + 1) / 2) * W, ((1 - v.y) / 2) * H]
  }

  it('frames the whole desk rectangle, every device and a standing figure, with room to spare', () => {
    fitCamera(cam, W, H, roomShot(W, H))
    const points: Vec3[] = [[0, 0, 0], [1.6, 0, 0], [0, 1.1, 0], [1.6, 1.1, 0], [0.4, 0.3, FIGURE_HEIGHT_M], [1.2, 0.3, FIGURE_HEIGHT_M]]
    for (const n of Object.values(NODES)) points.push(n.xyz)
    for (const p of points) {
      const [x, y] = px(p)
      expect(x).toBeGreaterThan(24)
      expect(x).toBeLessThan(W - 24)
      expect(y).toBeGreaterThan(24)
      expect(y).toBeLessThan(H - 24)
    }
    // north stays up: the desk's back edge is above the strip's aisle edge
    expect(px([0.8, 1.1, 0])[1]).toBeLessThan(px([0.8, 0, 0])[1])
  })

  it('lays the three links between Pi A and Pi B side by side, and the two Pi A to Board links apart', () => {
    const shifts = laneShifts(LINK_IDS)
    const piPair = ['pi5>pi5b:wifi', 'pi5>pi5b:ble', 'pi5b>pi5:ble'].map((id) => shifts.get(id)!)
    // the reverse link's shift is to its own left, so measured along pi5 -> pi5b it flips sign
    const along = [piPair[0], piPair[1], -piPair[2]]
    expect(new Set(along.map((v) => v.toFixed(3))).size).toBe(3)
    expect([shifts.get('pi5>unoq:wifi'), shifts.get('pi5>unoq:ble')]).toEqual([0.035, -0.035])
    expect(shifts.get('east>unoq:ble')).toBe(0)
  })

  it('puts each zone\'s no-movement word outside the strip on its own side, level with its name', () => {
    const [[x1, y1], west1] = alertWordAt(1)
    const [[x2, y2], west2] = alertWordAt(2)
    expect([x1, y1, west1]).toEqual([-0.08, 0.2, true])
    expect(x2).toBeCloseTo(1.68)
    expect([y2, west2]).toEqual([0.2, false])
  })

  it('stands the desk devices on the desk and the aisle beacons on the floor', () => {
    expect(standBase(NODES.pi5.xyz)).toEqual([0.8, 1.1, DESK_TOP_M])
    expect(standBase(NODES.unoq.xyz)).toEqual([1.1, 0.6, DESK_TOP_M])
    expect(standBase(NODES.east.xyz)).toEqual([1.6, 0.25, 0])
  })

  it('draws the six links that cross the strip in full and the six between desk devices faint, from the layout alone', () => {
    const onFloor = LINK_IDS.filter((id) => {
      const [tx, rx] = id.split(':')[0].split('>')
      return overFloor(NODES[tx].xyz, NODES[rx].xyz)
    })
    expect(onFloor.sort()).toEqual(['east>pi5:ble', 'east>pi5b:ble', 'east>unoq:ble', 'west>pi5:ble', 'west>pi5b:ble', 'west>unoq:ble'])
  })

  it('lays the X-ray on the strip\'s floor and on the desk top, one image across both, nothing past the desk', () => {
    // The mocks' 16 x 12 grid at 0.125 m from (-0.2, -0.2): 2 m by 1.5 m.
    const g = xrayGeometry([-0.2, -0.2], [2, 1.5])
    const pos = g.getAttribute('position')
    const uv = g.getAttribute('uv')
    const heights = new Set<number>()
    let northmost = -Infinity
    for (let i = 0; i < pos.count; i++) {
      heights.add(Number(pos.getY(i).toFixed(3)))
      const north = SIZE_M[1] / 2 - pos.getZ(i) // back to contract y
      northmost = Math.max(northmost, north)
      // the image's v runs with contract y across both parts
      expect(uv.getY(i)).toBeCloseTo((north + 0.2) / 1.5)
    }
    expect([...heights].sort()).toEqual([0.002, Number((DESK_TOP_M + 0.002).toFixed(3))])
    expect(northmost).toBeCloseTo(1.1)
  })

  it('puts the tray\'s tag on the desk top with it, not on the floor under the desk', () => {
    expect(objectTagAt([0.86, 1.0])[2]).toBeCloseTo(DESK_TOP_M + 0.08)
    expect(objectTagAt([0.8, 0.3])[2]).toBeCloseTo(0.08) // an object in the strip stays on the floor
  })
})
