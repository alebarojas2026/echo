import { Mesh, MeshBasicMaterial, RingGeometry, Shape, ShapeGeometry } from 'three'
import type { Advice } from './contract'
import { HOME_SPOT, ROUTER_SPOTS, SIZE_M, spotName } from './frame'
import { ACTION, EDGE, TEXT } from './palette'
import { standBase, v3 } from './stage'
import { fade } from './motion'
import type { RoomView } from './view'

// Floor marks for the router spots (contract section 3) and, while advice is set, a green arrow on the
// floor from S-home to advice.to_spot. Green means "something to do": move the router this way.

/** Which way is out from the spots' edge: south of the square's south edge, north of the desk's back edge. The
 *  arrow lies 13 cm out from the spots, clear of their rings; the tags 26 cm out. */
function outward(y: number): number {
  return y > SIZE_M[1] / 2 ? 1 : -1
}

/** The arrow to draw for this advice and router spot: from S-home to the advised spot, or null. */
export function adviceArrow(advice: Advice | null, router: string): { from: string; to: string; done: boolean } | null {
  if (!advice || !ROUTER_SPOTS[advice.to_spot] || advice.to_spot === HOME_SPOT) return null
  return { from: HOME_SPOT, to: advice.to_spot, done: router === advice.to_spot }
}

/** Whether a spot's ring is drawn: the router's own spot always; the others only while advice runs between them,
 *  so spare marks never sit unexplained under the devices. */
export function spotShown(id: string, router: string, arrow: ReturnType<typeof adviceArrow>): boolean {
  return id === router || (!!arrow && (id === arrow.to || id === arrow.from))
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
  private readonly meshes = new Map<string, Mesh>()
  private readonly arrow: Mesh<ShapeGeometry, MeshBasicMaterial>
  private arrowKey = ''
  /** Spot tags stay hidden until there is advice; then only the advised spot says where to put the router. */
  private readonly tags = new Map<string, HTMLElement>()
  private grow = 0 // 0..1, the arrow draws itself in
  private opacityTo = 0.9
  private growTo = 0

  constructor(private readonly view: RoomView) {
    const ring = new RingGeometry(0.04, 0.055, 32)
    for (const [id, [x, y]] of Object.entries(ROUTER_SPOTS)) {
      const mat = new MeshBasicMaterial({ color: EDGE })
      const mesh = new Mesh(ring, mat)
      mesh.rotation.x = -Math.PI / 2
      mesh.position.copy(v3([x, y, standBase([x, y, 0])[2] + 0.003])) // on the floor, or on the desk top
      view.scene.add(mesh)
      mesh.visible = id === HOME_SPOT
      this.rings.set(id, mat)
      this.meshes.set(id, mesh)
      const tag = view.addLabel(spotName(id), v3([x, y + 0.26 * outward(y), standBase([x, y, 0])[2]]), 'room-label--spot')
      tag.hidden = true
      this.tags.set(id, tag)
    }
    this.arrow = new Mesh(arrowGeometry(0.3), new MeshBasicMaterial({ color: ACTION, transparent: true, depthWrite: false }))
    this.arrow.rotation.x = -Math.PI / 2
    this.arrow.visible = false
    view.scene.add(this.arrow)
    view.addAnimator((dt) => this.ease(dt))
  }

  /** True while a spot's tag ("Move router here, ...") is on screen. */
  get tagShown(): boolean {
    return [...this.tags.values()].some((tag) => !tag.hidden)
  }

  update(router: string, advice: Advice | null) {
    const arrow = adviceArrow(advice, router)
    for (const [id, mat] of this.rings) {
      mat.color.setHex(id === router ? TEXT : EDGE)
      this.meshes.get(id)!.visible = spotShown(id, router, arrow)
    }
    this.view.host.dataset.adviceArrow = arrow ? arrow.to : ''
    for (const [id, tag] of this.tags) {
      tag.hidden = !arrow || id !== arrow.to
      if (!tag.hidden) tag.textContent = `${arrow!.done ? 'Router moved here' : 'Move router here'}, ${spotName(id)}`
    }
    this.growTo = arrow ? 1 : 0
    if (arrow) {
      const key = `${arrow.from}>${arrow.to}`
      if (key !== this.arrowKey) {
        this.arrowKey = key
        const [fx, fy] = ROUTER_SPOTS[arrow.from]
        const [tx] = ROUTER_SPOTS[arrow.to]
        // On the floor just outside the spots; on the desk, on its top just inside the back edge they sit on.
        const lift = standBase([fx, fy, 0])[2]
        const arrowY = fy + 0.13 * (lift > 0 ? -outward(fy) : outward(fy))
        const start = v3([fx, arrowY, lift + 0.004])
        const end = v3([tx, arrowY, lift + 0.004])
        this.arrow.geometry.dispose()
        this.arrow.geometry = arrowGeometry(start.distanceTo(end))
        this.arrow.position.copy(start)
        // Lying flat, the shape's +x points along the move (west or east).
        this.arrow.rotation.z = end.x < start.x ? Math.PI : 0
        this.grow = 0
      }
      this.opacityTo = arrow.done ? 0.4 : 0.9
    }
    this.view.requestRender()
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 260)
    this.grow += (this.growTo - this.grow) * k
    if (Math.abs(this.growTo - this.grow) < 0.005) this.grow = this.growTo
    this.arrow.visible = this.grow > 0
    this.arrow.scale.set(Math.max(this.grow, 0.001), 1, 1)
    const m = this.arrow.material
    m.opacity = fade(m.opacity, this.opacityTo, dt)
    return this.grow !== this.growTo || m.opacity !== this.opacityTo
  }
}
