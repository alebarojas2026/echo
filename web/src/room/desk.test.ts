import { PerspectiveCamera, Vector3 } from 'three'
import { beforeAll, describe, expect, it } from 'vitest'
import { laneShifts } from './beams'
import { FIGURE_HEIGHT_M } from './figure'
import { LINK_IDS, NODES, alertWordAt, applyLayout, toScene, type Vec3 } from './frame'
import { DESK_LAYOUT } from './layouts.fixture'
import { DESK_TOP_M, standBase } from './stage'
import { FOV_DEG, fitCamera, roomShot } from './view'

// The whole room on the desk layout of the contract PR (#415): this file applies it once; every other test file
// keeps the built-in square.
beforeAll(() => {
  expect(applyLayout(DESK_LAYOUT)).toBe(true)
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

  it('stands the desk devices on the desk and the aisle beacons on arms from its edge', () => {
    expect(standBase(NODES.pi5.xyz)).toEqual([0.8, 1.1, DESK_TOP_M])
    expect(standBase(NODES.unoq.xyz)).toEqual([1.1, 0.6, DESK_TOP_M])
    expect(standBase(NODES.east.xyz)).toEqual([1.6, 0.6, 1.0])
  })
})
