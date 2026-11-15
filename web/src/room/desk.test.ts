import { PerspectiveCamera, Vector3 } from 'three'
import { beforeAll, describe, expect, it } from 'vitest'
import { laneShifts, overFloor } from './beams'
import { demoScene } from './demo'
import { objectTagAt } from './ghost'
import { buildState, mockState } from './mock'
import { FIGURE_HEIGHT_M } from './figure'
import { LINK_IDS, NODES, SIZE_M, alertWordAt, applyLayout, nodeLabelSide, toScene, type Vec3 } from './frame'
import { DESK_LAYOUT } from './layouts.fixture'
import { clearBox, ghostBox } from './scan'
import { DESK_TOP_M, standBase, standOn } from './stage'
import { adviceShown, spotWords } from './spots'
import { FOV_DEG, deskAnchors, fitCamera, inSituShot, roomShot } from './view'
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

  it('frames the strip and desk large on a laptop (an 800 x 900 canvas beside the panels), centred, every word on it', () => {
    const [w, h] = [800, 900]
    const c = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
    fitCamera(c, w, h, roomShot(w, h))
    const at = (p: Vector3) => {
      const v = p.clone().project(c)
      return [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h]
    }
    // The strip's aisle edge takes most of the canvas's width (45% when it was framed like the square).
    const [x0] = at(new Vector3(...toScene([0, 0, 0])))
    const [x1] = at(new Vector3(...toScene([1.6, 0, 0])))
    expect(x1 - x0).toBeGreaterThan(0.65 * w)
    // Every device with its name, a head anywhere in the strip and the words in the aisle are on the canvas, with
    // as much room on one side as on the other (24 px edges, and the legend's 72 px row at the bottom).
    const reach = deskAnchors().map((a) => {
      const [x, y] = at(a.at)
      return { left: x - a.left, right: x + a.right, top: y - a.up, bottom: y + a.down }
    })
    const left = Math.min(...reach.map((r) => r.left)) - 24
    const right = w - 24 - Math.max(...reach.map((r) => r.right))
    const top = Math.min(...reach.map((r) => r.top)) - 24
    const bottom = h - 72 - Math.max(...reach.map((r) => r.bottom))
    for (const room of [left, right, top, bottom]) expect(room).toBeGreaterThan(-1)
    expect(Math.abs(left - right)).toBeLessThan(2)
    expect(Math.abs(top - bottom)).toBeLessThan(2)
  })

  it('names each device on the desk above it, and each beacon over the aisle just below it, reading inward', () => {
    expect(['unoq', 'pi5', 'pi5b'].map((id) => nodeLabelSide(id))).toEqual(['above', 'above', 'above'])
    expect(nodeLabelSide('west')).toBe('below-right')
    expect(nodeLabelSide('east')).toBe('below-left')
  })

  it('puts each zone\'s no-movement word in the aisle, under the middle of its zone', () => {
    expect(alertWordAt(1)).toEqual([[0.4, -0.06, 0], 'south'])
    const [[x2, y2, z2], side2] = alertWordAt(2)
    expect(x2).toBeCloseTo(1.2)
    expect([y2, z2, side2]).toEqual([-0.06, 0, 'south'])
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

  it('puts "Move router here" beside the advised spot on the desk, reading away from the router, never across it', () => {
    expect(spotWords('S-W30')).toEqual({ at: [0.5, 1.1, DESK_TOP_M], side: 'west' })
    expect(spotWords('S-E30')).toEqual({ at: [1.1, 1.1, DESK_TOP_M], side: 'east' })
  })

  it('drops the arrow and its words on the desk once the router stands on the advised spot', () => {
    expect(adviceShown({ from: 'S-home', to: 'S-W30', done: false })).toBe(true)
    expect(adviceShown({ from: 'S-home', to: 'S-W30', done: true })).toBe(false)
    expect(adviceShown(null)).toBe(false)
  })

  it('puts the tray\'s tag on the desk top with it, not on the floor under the desk', () => {
    expect(objectTagAt([0.86, 1.0])[2]).toBeCloseTo(DESK_TOP_M + 0.08)
    expect(objectTagAt([0.8, 0.3])[2]).toBeCloseTo(0.08) // an object in the strip stays on the floor
  })
})

describe('the desk inside the hall model', () => {
  const at = (x: number, y: number, z: number) => new Vector3(...toScene([x, y, z]))

  it('keeps the strip clear of the hall\'s furniture up to above head height, and stops short of the desk', () => {
    const box = clearBox()
    expect(box.containsPoint(at(0.05, 0.05, 0.5))).toBe(true) // a chair in the strip's corner
    expect(box.containsPoint(at(1.55, 0.55, 1.2))).toBe(true)
    expect(box.containsPoint(at(-0.2, -0.2, 0.9))).toBe(true) // a chair straddling the west end, toward the aisle
    expect(box.containsPoint(at(0.8, 0.6, 0.5))).toBe(false) // the desk begins
    expect(box.containsPoint(at(0.8, 0.3, -0.02))).toBe(false) // the floor stays
  })

  it('draws only the next row behind the strip see-through: never the strip, our desk or the floor', () => {
    const ghost = ghostBox()
    expect(ghost.containsPoint(at(0.8, -0.6, 0.7))).toBe(true) // the next row's desk, behind the person
    expect(ghost.containsPoint(at(0.8, 0.3, 0.7))).toBe(false)
    expect(ghost.containsPoint(at(0.8, 0.9, 0.7))).toBe(false)
    expect(ghost.containsPoint(at(0.8, -0.6, -0.02))).toBe(false)
  })

  it('frames the close view in situ: 45 degrees up, the rows around in view, every word on the canvas', () => {
    for (const [w, h] of [[1280, 1080], [800, 900]]) {
      const shot = inSituShot(w, h)
      expect(shot.elevDeg).toBe(45)
      expect(shot.radiusM).toBeGreaterThanOrEqual(1.7 * Math.min(1, w / 1280) - 1e-9)
      const c = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
      fitCamera(c, w, h, shot)
      for (const a of deskAnchors(1.7)) {
        const v = a.at.clone().project(c)
        const [x, y] = [((v.x + 1) / 2) * w, ((1 - v.y) / 2) * h]
        expect(x - a.left).toBeGreaterThan(23)
        expect(x + a.right).toBeLessThan(w - 23)
        expect(y - a.up).toBeGreaterThan(23)
        expect(y + a.down).toBeLessThan(h - 71)
      }
    }
  })
})

describe('devices wherever nodes.json puts them, inside a model of the room', () => {
  // A room model's surfaces, as heights under a point: our desk north of the strip, the next row's desk a third
  // of a metre behind it, the floor a little under ours everywhere else.
  const under = (_x: number, y: number) => (y >= 0.6 ? 0.72 : y <= -0.33 && y >= -0.93 ? 0.72 : -0.03)

  it('stands a device on our desk, on the next row’s desk, or free on the floor, by what is under it', () => {
    expect(standOn([0.8, 1.1, 1.0], under)).toEqual([0.8, 1.1, 0.72])
    expect(standOn([0.8, -0.6, 1.05], under)).toEqual([0.8, -0.6, 0.72])
    expect(standOn([0.3, -0.15, 1.1], under)).toEqual([0.3, -0.15, -0.03])
  })

  it('stands a device on a desk’s very edge on the desk, not on the floor beside it', () => {
    expect(standOn([1.1, 0.58, 1.0], under)[2]).toBe(0.72)
  })

  it('never stands a device on something above it, and uses our floor where the model has nothing', () => {
    expect(standOn([0.8, 1.0, 0.5], under)[2]).toBe(0)
    expect(standOn([0.8, 0.3, 1.0], () => null)).toEqual([0.8, 0.3, 0])
  })
})
