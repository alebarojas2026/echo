import { PerspectiveCamera, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { NODES, SQUARE_M, toScene, type Vec3 } from './frame'
import { FOV_DEG, fitCamera, roomShot } from './view'

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
  const s = SQUARE_M
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
    const s = SQUARE_M
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
    expect(roomShot(W, H).radiusM).toBeCloseTo(1.45 * (SQUARE_M / 2))
  })
})
