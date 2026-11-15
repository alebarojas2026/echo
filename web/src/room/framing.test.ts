import { PerspectiveCamera, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { NODES, SIZE_M, STRIP_M, toScene, type Vec3 } from './frame'
import { mixShot } from './fly'
import { FOV_DEG, fitCamera, judgeShot, roomShot } from './view'

// The room's canvas on the 1920x1080 kiosk: everything right of the panels' 640 px rail.
const W = 1280
const H = 1080

function camera() {
  const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
  fitCamera(cam, W, H)
  return cam
}

function px(cam: PerspectiveCamera, p: Vec3): [number, number] {
  const v = new Vector3(...toScene(p)).project(cam)
  return [((v.x + 1) / 2) * W, ((1 - v.y) / 2) * H]
}

describe('room framing at 1280 x 1080', () => {
  const cam = camera()
  const s = SIZE_M[0]
  const [sw, se, nw, ne] = ([[0, 0, 0], [s, 0, 0], [0, s, 0], [s, s, 0]] as Vec3[]).map((p) => px(cam, p))

  it('shows north straight up: the square is not turned', () => {
    expect(Math.abs(sw[1] - se[1])).toBeLessThan(0.5) // south edge level
    expect(Math.abs(nw[1] - ne[1])).toBeLessThan(0.5) // north edge level
    expect(nw[1]).toBeLessThan(sw[1]) // north is up the screen
    expect(nw[0]).toBeLessThan(ne[0]) // west is left
  })

  it('makes the square big: south edge at least 680 px wide, north edge at least 600 px', () => {
    expect(se[0] - sw[0]).toBeGreaterThanOrEqual(680)
    expect(ne[0] - nw[0]).toBeGreaterThanOrEqual(600)
  })

  it('keeps every node head well inside the canvas', () => {
    for (const node of Object.values(NODES)) {
      const [x, y] = px(cam, node.xyz)
      expect(x).toBeGreaterThan(24)
      expect(x).toBeLessThan(W - 24)
      expect(y).toBeGreaterThan(24 + 40) // room for a label above it
      expect(y).toBeLessThan(H - 24)
    }
  })
})

describe('room framing on a laptop, beside the panels rail', () => {
  // 1512x982, 1440x900 and 1280x800 screens leave these canvases right of the 640 px rail.
  const canvases: [number, number][] = [[872, 982], [800, 900], [640, 800]]

  it('keeps 200 px beside each beacon and the no-movement word, so their words stay on the canvas', () => {
    const s = SIZE_M[0]
    const anchors: Vec3[] = [[0, s / 2, 1], [s, s / 2, 1], [-0.08, 0.2, 0], [s + 0.08, 0.2, 0]]
    for (const [w, h] of canvases) {
      const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
      fitCamera(cam, w, h, roomShot(w, h))
      for (const a of anchors) {
        const v = new Vector3(...toScene(a)).project(cam)
        const x = ((v.x + 1) / 2) * w
        expect(Math.min(x, w - x)).toBeGreaterThanOrEqual(199)
      }
    }
  })

  it("doesn't change the 1920 x 1080 screen's framing", () => {
    expect(roomShot(W, H).radiusM).toBeCloseTo(roomShot().radiusM)
    expect(roomShot(W, H).radiusM).toBeCloseTo(1.45 * (SIZE_M[0] / 2))
  })
})

// The judge's view on the one spot (judgeShot): behind and above the spot, looking to the front of the hall.
describe('the judge\'s view of the one spot', () => {
  const eye = (front: [number, number], w = 1920, h = 1080) => {
    const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 100)
    const shot = judgeShot(() => front)(w, h)
    fitCamera(cam, w, h, shot)
    return { cam, shot }
  }
  const spotOnScreen = (cam: PerspectiveCamera) => {
    const [sw, sh] = STRIP_M ?? SIZE_M
    return new Vector3(...toScene([sw / 2, sh / 2, 0])).project(cam)
  }

  it('stands behind the spot, above it, and looks towards the front', () => {
    const { cam, shot } = eye([0, -20])
    expect(cam.position.z).toBeGreaterThan(3)
    expect(cam.position.y).toBeGreaterThan(2)
    expect(shot.target.z).toBeLessThan(-3)
    expect(shot.fovDeg).toBeGreaterThan(FOV_DEG)
  })

  it('keeps the spot right of the middle and above the words\' band, at both screen sizes', () => {
    for (const [w, h] of [[1920, 1080], [1440, 900]]) {
      const p = spotOnScreen(eye([0, -20], w, h).cam)
      expect(p.x).toBeGreaterThan(0.05)
      expect(p.x).toBeLessThan(0.45)
      // -1 is the bottom of the screen; the band is its lowest fifth and a little more.
      expect(p.y).toBeGreaterThan(-0.52)
      expect(p.y).toBeLessThan(-0.2)
    }
  })

  it('follows the hall: with the front another way, the spot is framed the same', () => {
    const north = spotOnScreen(eye([0, -20]).cam)
    for (const front of [[20, 0], [-14, 14], [3, 20]] as [number, number][]) {
      const { cam } = eye(front)
      const p = spotOnScreen(cam)
      expect(p.x).toBeCloseTo(north.x, 2)
      expect(p.y).toBeCloseTo(north.y, 2)
      // The camera is on the far side of the spot from the front.
      expect(cam.position.x * front[0] + cam.position.z * front[1]).toBeLessThan(0)
    }
  })

  it('a fly to it changes the lens evenly, and other flies carry none', () => {
    const a = roomShot()
    const b = judgeShot(() => [0, -20])(1920, 1080)
    expect(mixShot(a, b, 0.5).fovDeg).toBeCloseTo((FOV_DEG + b.fovDeg!) / 2)
    expect('fovDeg' in mixShot(a, a, 0.5)).toBe(false)
    const cam = new PerspectiveCamera(77, 1, 0.1, 100)
    fitCamera(cam, 1280, 1080, a)
    expect(cam.fov).toBe(FOV_DEG)
  })
})
