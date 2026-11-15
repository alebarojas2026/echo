import { Mesh, MeshBasicMaterial, RingGeometry, Shape, ShapeGeometry } from 'three'
import type { Advice } from './contract'
import { deviceAcross, HOME_SPOT, ROUTER_SPOTS, SIZE_M, spotName, type Vec3 } from './frame'
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

/**
 * The arrow to draw for this advice and router spot: from S-home to the advised spot, or null. Never on a layout
 * with a device across the spot (the gate): there the router is cabled to the board's hub and can't be moved, so
 * nothing on the room may tell anyone to move it. The dead zone is then something left standing in the line, and
 * the cure is taking it away (#789).
 */
export function adviceArrow(advice: Advice | null, router: string): { from: string; to: string; done: boolean } | null {
  if (deviceAcross()) return null
  if (!advice || !advice.to_spot || !ROUTER_SPOTS[advice.to_spot] || advice.to_spot === HOME_SPOT) return null
  return { from: HOME_SPOT, to: advice.to_spot, done: router === advice.to_spot }
}

/**
 * Where an advised spot's words go and which way they read. On a desk: just above the spot's ring, in two short
 * lines that read away from the router's home, so "Move router here" never lies across the router or its name
 * and stays on a laptop's narrower canvas. On the floor (the square): 26 cm outside the square's edge, centred,
 * in one line, as before.
 */
export function spotWords(id: string): { at: Vec3; side: 'west' | 'east' | 'centre' } {
  const [x, y] = ROUTER_SPOTS[id]
  const top = standBase([x, y, 0])[2]
  if (top <= 0) return { at: [x, y + 0.26 * outward(y), 0], side: 'centre' }
  const homeX = ROUTER_SPOTS[HOME_SPOT]?.[0] ?? x
  return { at: [x, y, top], side: x < homeX ? 'west' : 'east' }
}

/** Whether the arrow and its words still show. On a desk they go once the router stands on the advised spot: the
 *  router and its name are there now, and the words would lie across them (the panels say the move was made). On
 *  the floor they stay, dimmer, as before. */
export function adviceShown(arrow: ReturnType<typeof adviceArrow>): boolean {
  return !!arrow && !(arrow.done && spotWords(arrow.to).side !== 'centre')
}

/** Whether a spot's ring is drawn: only while advice runs between two spots, and then only those two. With no
 *  advice a ring is a circle nobody can read (it sat under the router, or alone on the floor when the router
 *  stands somewhere the room has no desk for). */
export function spotShown(id: string, arrow: ReturnType<typeof adviceArrow>): boolean {
  return !!arrow && (id === arrow.to || id === arrow.from)
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
      mesh.visible = false
      this.rings.set(id, mat)
      this.meshes.set(id, mesh)
      const words = spotWords(id)
      const tag = view.addLabel(spotName(id), v3(words.at), `room-label--spot${words.side === 'centre' ? '' : ` room-label--spot-${words.side}`}`)
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
      this.meshes.get(id)!.visible = spotShown(id, arrow)
    }
    this.view.host.dataset.adviceArrow = arrow ? arrow.to : ''
    for (const [id, tag] of this.tags) {
      tag.hidden = !adviceShown(arrow) || id !== arrow!.to
      // On a desk the distance goes on its own line (room-label--spot-west / -east keep line breaks).
      const lines = tag.classList.contains('room-label--spot-west') || tag.classList.contains('room-label--spot-east')
      if (!tag.hidden) tag.textContent = `${arrow!.done ? 'Router moved here' : 'Move router here'},${lines ? '\n' : ' '}${spotName(id)}`
    }
    this.growTo = adviceShown(arrow) ? 1 : 0
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
