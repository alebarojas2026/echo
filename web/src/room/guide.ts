import { BoxGeometry, EdgesGeometry, LineBasicMaterial, LineSegments } from 'three'
import type { Placement } from './desks'
import { NODES, type Vec3 } from './frame'
import { TEXT } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// The placement guide in the 3D view (align mode only, never on a judge's screen): where each device should go at
// the chosen desk (desks.ts, placementGuide), as a faint outlined box with "<name> here". One can be picked (Tab)
// and moved by hand; S saves the positions, and from then on the devices are drawn there.

const BOX_M = 0.1
const CLOSE_M = 0.25
const STEP_M = 0.05
const BIG_STEP_M = 0.2

interface Mark {
  id: string
  xyz: Vec3
  /** The guide's own words for it, until it is moved by hand. */
  words: string
  moved: boolean
  box: LineSegments<EdgesGeometry, LineBasicMaterial>
  label: HTMLElement
}

/** How a device moved by hand is described: the numbers someone could measure from the spot's west corner. */
export function handWords(name: string, [x, y, z]: Vec3): string {
  return `${name}: placed by hand, ${x.toFixed(2)} m east, ${y.toFixed(2)} m north, ${z.toFixed(2)} m high`
}

/** The position after one key press on a picked device, or null when the key isn't one of its keys. Arrows move it
 *  on the floor plan (5 cm, Shift 20 cm); PageUp and PageDown raise and lower it; never below the floor. */
export function nudgePlace([x, y, z]: Vec3, key: string, shift: boolean): Vec3 | null {
  const s = shift ? BIG_STEP_M : STEP_M
  const r = (v: number) => Math.round(v * 100) / 100
  switch (key) {
    case 'ArrowRight': return [r(x + s), y, z]
    case 'ArrowLeft': return [r(x - s), y, z]
    case 'ArrowUp': return [x, r(y + s), z]
    case 'ArrowDown': return [x, r(y - s), z]
    case 'PageUp': return [x, y, r(z + s)]
    case 'PageDown': return [x, y, Math.max(0, r(z - s))]
  }
  return null
}

export class PlacementGuide {
  private marks: Mark[] = []
  private picked: string | null = null
  private visible = false

  constructor(private readonly view: RoomView) {}

  /** True while the guide is on screen. */
  get shown(): boolean {
    return this.visible
  }

  /** The picked device's id, or null. */
  get selected(): string | null {
    return this.visible ? this.picked : null
  }

  /** Shows the guide for these placements (a new desk or side starts every device from the guide again). */
  show(places: readonly Placement[]) {
    this.hide()
    for (const p of places) {
      let mark = this.marks.find((m) => m.id === p.id)
      if (!mark) {
        const mat = new LineBasicMaterial({ color: TEXT, transparent: true, opacity: 0.6, depthTest: false })
        const box = new LineSegments(new EdgesGeometry(new BoxGeometry(BOX_M, BOX_M, BOX_M)), mat)
        box.renderOrder = 30
        this.view.scene.add(box)
        const label = this.view.addLabel(`${NODES[p.id]?.name ?? p.id} here`, v3(p.xyz), 'room-label--guide')
        mark = { id: p.id, xyz: p.xyz, words: p.words, moved: false, box, label }
        this.marks.push(mark)
      }
      mark.xyz = [...p.xyz]
      mark.words = p.words
      mark.moved = false
    }
    this.visible = true
    this.picked = null
    this.draw()
  }

  hide() {
    this.visible = false
    this.picked = null
    this.draw()
  }

  /** Tab: the next device, then none. */
  cycle() {
    const ids = this.marks.map((m) => m.id)
    const i = this.picked ? ids.indexOf(this.picked) : -1
    this.picked = ids[i + 1] ?? null
    this.draw()
  }

  release() {
    this.picked = null
    this.draw()
  }

  /** Moves the picked device by one key press. Returns false when the key isn't one of its keys. */
  nudge(key: string, shift: boolean): boolean {
    const mark = this.marks.find((m) => m.id === this.picked)
    const next = mark && nudgePlace(mark.xyz, key, shift)
    if (!mark || !next) return false
    mark.xyz = next
    mark.moved = true
    this.draw()
    return true
  }

  /** Every device's position as shown, for saving. */
  positions(): { id: string; xyz_m: Vec3 }[] {
    return this.marks.map((m) => ({ id: m.id, xyz_m: m.xyz }))
  }

  /** One line per device: the guide's words, or where it was put by hand. The picked one is marked. */
  lines(): string[] {
    return this.marks.map((m) => `${m.id === this.picked ? '▸ ' : ''}${m.moved ? handWords(NODES[m.id]?.name ?? m.id, m.xyz) : m.words}`)
  }

  private draw() {
    for (const m of this.marks) {
      const on = this.visible
      const picked = on && m.id === this.picked
      m.box.visible = on
      m.box.position.copy(v3(m.xyz))
      m.box.material.opacity = picked ? 1 : 0.6
      m.label.hidden = !on
      m.label.classList.toggle('room-label--guide-picked', picked)
      // Two places side by side (the board and the router): their words read outward from each other.
      const beside = this.marks.find((o) => o !== m && Math.abs(o.xyz[0] - m.xyz[0]) < CLOSE_M && Math.abs(o.xyz[1] - m.xyz[1]) < CLOSE_M)
      m.label.classList.toggle('room-label--guide-west', !!beside && m.xyz[0] <= beside.xyz[0] && (m.xyz[0] < beside.xyz[0] || m.id < beside.id))
      m.label.classList.toggle('room-label--guide-east', !!beside && !m.label.classList.contains('room-label--guide-west'))
      // Above the box, like a device's own name.
      this.view.moveLabel(m.label, v3([m.xyz[0], m.xyz[1], m.xyz[2] + BOX_M / 2]))
    }
    this.view.requestRender()
  }
}
