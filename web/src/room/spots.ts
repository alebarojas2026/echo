import { Mesh, MeshBasicMaterial, RingGeometry, Shape, ShapeGeometry } from 'three'
import type { Advice } from './contract'
import { HOME_SPOT, ROUTER_SPOTS, spotName } from './frame'
import { ACTION, EDGE, TEXT } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// Floor marks for the router spots (contract section 3) and, while advice is set, a green arrow on the
// floor from S-home to advice.to_spot. Green means "something to do": move the router this way.

const ARROW_Y_M = -0.13 // just south of the square's edge, clear of the spot rings

/** The arrow to draw for this advice and router spot: from S-home to the advised spot, or null. */
export function adviceArrow(advice: Advice | null, router: string): { from: string; to: string; done: boolean } | null {
  if (!advice || !ROUTER_SPOTS[advice.to_spot] || advice.to_spot === HOME_SPOT) return null
  return { from: HOME_SPOT, to: advice.to_spot, done: router === advice.to_spot }
}

/** A flat arrow along +x, `len` metres long, lying in the shape's XY plane. */
function arrowGeometry(len: number): ShapeGeometry {
  const head = Math.min(0.08, len * 0.45)
  const shaft = 0.014
  const wing = 0.045
  const s = new Shape()
  s.moveTo(0, -shaft)
  s.lineTo(len - head, -shaft)
  s.lineTo(len - head, -wing)
  s.lineTo(len, 0)
  s.lineTo(len - head, wing)
  s.lineTo(len - head, shaft)
  s.lineTo(0, shaft)
  s.closePath()
  return new ShapeGeometry(s)
}

export class RouterSpots {
  private readonly rings = new Map<string, MeshBasicMaterial>()
  private readonly arrow: Mesh<ShapeGeometry, MeshBasicMaterial>
  private arrowKey = ''
  private grow = 0 // 0..1, the arrow draws itself in
  private growTo = 0

  constructor(private readonly view: RoomView) {
    const ring = new RingGeometry(0.04, 0.055, 32)
    for (const [id, [x, y]] of Object.entries(ROUTER_SPOTS)) {
      const mat = new MeshBasicMaterial({ color: EDGE })
      const mesh = new Mesh(ring, mat)
      mesh.rotation.x = -Math.PI / 2
      mesh.position.copy(v3([x, y, 0.003]))
      view.scene.add(mesh)
      this.rings.set(id, mat)
      view.addLabel(spotName(id), v3([x, y - 0.26, 0]), 'room-label--spot')
    }
    this.arrow = new Mesh(arrowGeometry(0.3), new MeshBasicMaterial({ color: ACTION, transparent: true, depthWrite: false }))
    this.arrow.rotation.x = -Math.PI / 2
    this.arrow.visible = false
    view.scene.add(this.arrow)
    view.addAnimator((dt) => this.ease(dt))
  }

  update(router: string, advice: Advice | null) {
    for (const [id, mat] of this.rings) mat.color.setHex(id === router ? TEXT : EDGE)
    const arrow = adviceArrow(advice, router)
    this.view.host.dataset.adviceArrow = arrow ? arrow.to : ''
    this.growTo = arrow ? 1 : 0
    if (arrow) {
      const key = `${arrow.from}>${arrow.to}`
      if (key !== this.arrowKey) {
        this.arrowKey = key
        const [fx] = ROUTER_SPOTS[arrow.from]
        const [tx] = ROUTER_SPOTS[arrow.to]
        const start = v3([fx, ARROW_Y_M, 0.004])
        const end = v3([tx, ARROW_Y_M, 0.004])
        this.arrow.geometry.dispose()
        this.arrow.geometry = arrowGeometry(start.distanceTo(end))
        this.arrow.position.copy(start)
        // Lying flat, the shape's +x points along the move (west or east).
        this.arrow.rotation.z = end.x < start.x ? Math.PI : 0
        this.grow = 0
      }
      this.arrow.material.opacity = arrow.done ? 0.4 : 0.9
    }
    this.view.requestRender()
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 260)
    this.grow += (this.growTo - this.grow) * k
    if (Math.abs(this.growTo - this.grow) < 0.005) this.grow = this.growTo
    this.arrow.visible = this.grow > 0
    this.arrow.scale.set(Math.max(this.grow, 0.001), 1, 1)
    return this.grow !== this.growTo
  }
}
