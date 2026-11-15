import { BoxGeometry, BufferGeometry, Float32BufferAttribute, LineBasicMaterial, LineSegments, Mesh, MeshBasicMaterial, Plane, Raycaster, Vector2, Vector3 } from 'three'
import type { HallLink } from './contract'
import { HALL_BEACONS, SIZE_M, type HallBeacon, type Vec3 } from './frame'
import { fade, Held } from './motion'
import { EDGE, TEXT } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// Hall beacons: radios far outside the layout (nodes.json hall.beacons). Like every device they are drawn only
// while the board hears them (a hall row from them that isn't stale) and only where someone has placed them. A
// beacon that is heard but has no position yet waits in a small tray ("1 new beacon: H"). In align mode a beacon
// can be picked (Tab, or a click on it), moved (arrows, or dragged, from the tray too) and saved with S.

const HEAD_M = 0.12
/** The height a beacon gets when it is placed by hand: the contract's antennas are 1 m up. */
const PLACED_Z_M = 1.0
const ON_MS = 300
const OFF_MS = 2500

/** The hall beacons heard now: a hall row from them with readings that isn't stale. */
export function hallHeard(rows: readonly HallLink[] | undefined): Set<string> {
  return new Set((rows ?? []).filter((r) => !r.stale && (r.rate_hz ?? 0) > 0).map((r) => r.tx))
}

/** The tray's words for heard beacons with no position: "1 new beacon: H", "2 new beacons: H, J", or ''. */
export function trayText(waiting: readonly HallBeacon[]): string {
  if (!waiting.length) return ''
  return `${waiting.length} new beacon${waiting.length > 1 ? 's' : ''}: ${waiting.map((b) => b.id).join(', ')}`
}

interface Item {
  b: HallBeacon
  head: Mesh<BoxGeometry, MeshBasicMaterial>
  post: LineSegments<BufferGeometry, LineBasicMaterial>
  label: HTMLElement
  held: Held<boolean>
  heard: boolean
  alpha: number
}

export class HallBeacons {
  /** The beacon align mode is moving, or null. */
  selected: string | null = null
  private readonly items: Item[] = []
  private readonly tray: HTMLElement
  private editing = false
  private dragging: string | null = null
  private onChange: () => void = () => {}

  constructor(private readonly view: RoomView) {
    const geom = new BoxGeometry(HEAD_M, HEAD_M, HEAD_M)
    for (const b of HALL_BEACONS) {
      const head = new Mesh(geom, new MeshBasicMaterial({ color: TEXT, transparent: true, opacity: 0 }))
      const postGeom = new BufferGeometry()
      postGeom.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3))
      const post = new LineSegments(postGeom, new LineBasicMaterial({ color: EDGE, transparent: true, opacity: 0 }))
      head.visible = post.visible = false
      head.userData.beacon = b.node
      view.scene.add(head, post)
      const label = view.addLabel(`Beacon ${b.id}`, new Vector3(), 'room-label--node room-label--right')
      label.hidden = true
      this.items.push({ b, head, post, label, held: new Held<boolean>(false, (on) => (on ? ON_MS : OFF_MS)), heard: false, alpha: 0 })
    }
    this.tray = document.createElement('div')
    this.tray.className = 'room-tray'
    this.tray.hidden = true
    view.host.append(this.tray)
    for (const it of this.items) this.put(it)
    view.addAnimator((dt) => this.ease(dt))
  }

  /** Who is heard now (state.hall), held so a missed reading never makes a beacon blink. */
  update(rows: readonly HallLink[] | undefined, nowMs = performance.now()) {
    const now = hallHeard(rows)
    for (const it of this.items) it.heard = it.held.update(now.has(it.b.node), nowMs)
    this.refresh()
  }

  /** Align mode: the tray's beacons can be dragged onto the model, and placed ones clicked and dragged. */
  startEditing(onChange: () => void) {
    this.editing = true
    this.onChange = onChange
    const canvas = this.view.renderer.domElement
    canvas.addEventListener('pointerdown', (e) => {
      const hit = this.pick(e)
      if (!hit) return
      this.select(hit)
      this.dragging = hit
      canvas.setPointerCapture(e.pointerId)
    })
    canvas.addEventListener('pointermove', (e) => {
      if (this.dragging) this.dropAt(this.dragging, e)
    })
    window.addEventListener('pointerup', (e) => {
      if (this.dragging && e.target === canvas) this.dropAt(this.dragging, e)
      this.dragging = null
    })
    this.refresh()
  }

  /** The heard beacons, in file order: the ones Tab steps through. */
  heardNodes(): string[] {
    return this.items.filter((it) => it.heard).map((it) => it.b.node)
  }

  select(node: string | null) {
    this.selected = node
    for (const it of this.items) it.label.classList.toggle('room-label--selected', it.b.node === node)
    this.view.host.dataset.selected = node ?? ''
    this.onChange()
    this.view.requestRender()
  }

  /** Tab: the next heard beacon, then none. */
  cycle() {
    const nodes = this.heardNodes()
    const i = this.selected ? nodes.indexOf(this.selected) : -1
    this.select(i + 1 < nodes.length ? nodes[i + 1] : null)
  }

  /** Moves the selected beacon on the floor (contract metres, east and north). An unplaced one starts 2 m north
   *  of the layout. */
  nudge(dx: number, dy: number) {
    const it = this.items.find((i) => i.b.node === this.selected)
    if (!it) return
    const [x, y, z] = it.b.xyz ?? [SIZE_M[0] / 2, SIZE_M[1] + 2, PLACED_Z_M]
    this.place(it, [Number((x + dx).toFixed(2)), Number((y + dy).toFixed(2)), z])
  }

  /** Every beacon's position, for saving to nodes.json. */
  positions(): { node: string; xyz_m: Vec3 | null }[] {
    return this.items.map((it) => ({ node: it.b.node, xyz_m: it.b.xyz }))
  }

  /** Words for the align panel: the selected beacon and where it is. */
  describe(): string {
    const it = this.items.find((i) => i.b.node === this.selected)
    if (!it) return ''
    const at = it.b.xyz ? `${it.b.xyz[0].toFixed(2)} m east, ${it.b.xyz[1].toFixed(2)} m north` : 'not placed yet'
    return `Beacon ${it.b.id}: ${at}`
  }

  private place(it: Item, xyz: Vec3) {
    it.b.xyz = xyz
    this.put(it)
    this.refresh()
    this.onChange()
  }

  /** The beacon under the pointer, if any. */
  private pick(e: PointerEvent): string | null {
    const ray = this.ray(e)
    const heads = this.items.filter((it) => it.head.visible).map((it) => it.head)
    return (ray.intersectObjects(heads)[0]?.object.userData.beacon as string | undefined) ?? null
  }

  /** Puts `node` where the pointer meets the floor. */
  private dropAt(node: string, e: PointerEvent) {
    const it = this.items.find((i) => i.b.node === node)
    const hit = this.ray(e).ray.intersectPlane(new Plane(new Vector3(0, 1, 0), 0), new Vector3())
    if (!it || !hit) return
    // Scene back to the contract frame (frame.ts toScene, inverted).
    this.place(it, [Number((hit.x + SIZE_M[0] / 2).toFixed(2)), Number((SIZE_M[1] / 2 - hit.z).toFixed(2)), it.b.xyz?.[2] ?? PLACED_Z_M])
  }

  private ray(e: PointerEvent): Raycaster {
    const rect = this.view.renderer.domElement.getBoundingClientRect()
    const ndc = new Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    const ray = new Raycaster()
    ray.setFromCamera(ndc, this.view.camera)
    return ray
  }

  private put(it: Item) {
    if (!it.b.xyz) return
    const top = v3(it.b.xyz)
    it.head.position.copy(top)
    const base = v3([it.b.xyz[0], it.b.xyz[1], 0])
    const pos = it.post.geometry.getAttribute('position') as Float32BufferAttribute
    pos.set([base.x, base.y, base.z, top.x, top.y, top.z])
    pos.needsUpdate = true
    it.post.geometry.computeBoundingSphere()
    this.view.moveLabel(it.label, v3([it.b.xyz[0] + HEAD_M / 2, it.b.xyz[1], it.b.xyz[2]]))
  }

  /** The tray and the test mirror, after hearing or placing changes. */
  private refresh() {
    const waiting = this.items.filter((it) => it.heard && !it.b.xyz).map((it) => it.b)
    this.tray.replaceChildren()
    if (waiting.length) {
      const words = document.createElement('span')
      words.textContent = trayText(waiting)
      this.tray.append(words)
      // In align mode each waiting beacon is a chip to drag onto the model.
      if (this.editing) {
        for (const b of waiting) {
          const chip = document.createElement('button')
          chip.type = 'button'
          chip.className = 'room-tray-chip'
          chip.textContent = b.id
          chip.addEventListener('pointerdown', (e) => {
            e.preventDefault()
            this.select(b.node)
            this.dragging = b.node
          })
          this.tray.append(chip)
        }
      }
    }
    this.tray.hidden = !waiting.length
    this.view.host.dataset.hallBeacons = this.items.filter((it) => it.heard && it.b.xyz).map((it) => it.b.node).join(',')
    this.view.host.dataset.hallWaiting = waiting.map((b) => b.node).join(',')
    this.view.requestRender()
  }

  private ease(dt: number): boolean {
    let busy = false
    for (const it of this.items) {
      const to = it.heard && it.b.xyz ? 1 : 0
      it.alpha = fade(it.alpha, to, dt)
      busy ||= it.alpha !== to
      it.head.material.opacity = it.post.material.opacity = it.alpha
      it.head.visible = it.post.visible = it.alpha > 0
      it.head.scale.setScalar(it.b.node === this.selected ? 1.5 : 1)
      it.label.style.opacity = String(it.alpha)
      it.label.hidden = it.alpha === 0
    }
    return busy
  }
}
