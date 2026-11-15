import { Color, Mesh, MeshBasicMaterial, PlaneGeometry } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import type { Alert, Checkin } from './contract'
import { alertWordAt, zoneRect } from './frame'
import { FAULT, PERSON } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// The no-movement alert on the floor, and the wave check-in window.
//   counting  the alert zone gets a light amber fill and a 3 px outline (the person's colour: we're watching)
//   check_on  red fill and a 6 px outline; the fill breathes between 0.3 and 0.2 over 2 s
//             (held still under prefers-reduced-motion)

export const WAVE_MS = 6000

/**
 * Says whether a check-in is still being shown: true for 6 s after a check-in with a new t arrives.
 * The check-in already in the first state is old news, so it doesn't count. Board time and screen time
 * aren't compared; the window starts when the screen sees the new t.
 */
export class WaveClock {
  private lastT: number | null = null
  private primed = false
  private since = -Infinity
  link: string | null = null

  update(checkin: Checkin | null, now: number): boolean {
    const t = checkin?.t ?? null
    if (!this.primed) {
      this.primed = true
      this.lastT = t
    } else if (t !== null && t !== this.lastT) {
      this.lastT = t
      this.since = now
      this.link = checkin!.link
    }
    return now - this.since < WAVE_MS
  }
}

export interface AlertLook {
  zone: number | null
  color: number
  fill: number
  width: number
  breathe: boolean
}

export function alertLook(alert: Alert | null): AlertLook {
  if (!alert || alert.state === 'none' || !alert.zone || !zoneRect(alert.zone)) {
    return { zone: null, color: PERSON, fill: 0, width: 0, breathe: false }
  }
  return alert.state === 'check_on'
    ? { zone: alert.zone, color: FAULT, fill: 0.3, width: 6, breathe: true }
    : { zone: alert.zone, color: PERSON, fill: 0.15, width: 3, breathe: false }
}

export { alertWordAt } from './frame'

const INSET_M = 0.03 // the outline sits just inside the zone, clear of the square and zone lines

export class AlertMarks {
  private readonly fill: Mesh<PlaneGeometry, MeshBasicMaterial>
  private readonly line: Line2
  private readonly mat: LineMaterial
  private look: AlertLook = alertLook(null)
  private alpha = 0
  private width = 0
  private clock = 0
  private readonly still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  /** Red is a status colour, so the fired alert also says it in words, just outside the square by its zone. */
  private readonly word: HTMLElement

  constructor(private readonly view: RoomView) {
    // A unit plane, sized to the zone's rectangle when the alert moves there.
    this.fill = new Mesh(new PlaneGeometry(1, 1), new MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }))
    this.fill.rotation.x = -Math.PI / 2
    this.fill.renderOrder = -1
    this.fill.visible = false
    this.mat = new LineMaterial({ linewidth: 0, transparent: true })
    this.line = new Line2(new LineGeometry(), this.mat)
    this.line.visible = false
    view.scene.add(this.fill, this.line)
    view.onResize((w, h) => this.mat.resolution.set(w, h))
    this.word = view.addLabel('No movement', v3([0, 0, 0]), 'room-label--alert')
    this.word.hidden = true
    view.addAnimator((dt) => this.ease(dt))
  }

  update(alert: Alert | null) {
    const look = alertLook(alert)
    if (look.zone && look.zone !== this.look.zone) this.place(look.zone)
    this.look = look.zone ? look : { ...this.look, fill: 0, width: 0, breathe: false }
    if (look.zone) {
      this.fill.material.color.setHex(look.color)
      this.mat.color = new Color(look.color)
    }
    this.view.host.dataset.alertZone = look.zone ? String(look.zone) : ''
    this.word.hidden = alert?.state !== 'check_on' || !look.zone
    if (!this.word.hidden) {
      const [at, side] = alertWordAt(look.zone!)
      this.word.classList.toggle('room-label--alert-west', side === 'west')
      this.word.classList.toggle('room-label--alert-south', side === 'south')
      this.view.moveLabel(this.word, v3(at))
    }
    this.view.requestRender()
  }

  private place(zone: number) {
    const [x0, y0, x1, y1] = zoneRect(zone)!
    const cx = (x0 + x1) / 2
    const cy = (y0 + y1) / 2
    const hx = (x1 - x0) / 2 - INSET_M
    const hy = (y1 - y0) / 2 - INSET_M
    this.fill.position.copy(v3([cx, cy, 0.0015]))
    this.fill.scale.set(2 * hx - 2 * INSET_M, 2 * hy - 2 * INSET_M, 1)
    const pts = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy], [-hx, -hy]].flatMap(([dx, dy]) => {
      const p = v3([cx + dx, cy + dy, 0.005])
      return [p.x, p.y, p.z]
    })
    ;(this.line.geometry as LineGeometry).setPositions(pts)
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 140)
    this.clock += dt
    const breathing = this.look.breathe && !this.still
    // 0.3 -> 0.2 -> 0.3 over 2 s while the alert is on.
    const target = breathing ? 0.25 + 0.05 * Math.cos((2 * Math.PI * this.clock) / 2000) : this.look.fill
    this.alpha += (target - this.alpha) * k
    this.width += (this.look.width - this.width) * k
    if (!breathing && Math.abs(target - this.alpha) < 0.003) this.alpha = target
    if (Math.abs(this.look.width - this.width) < 0.05) this.width = this.look.width
    this.fill.material.opacity = this.alpha
    this.fill.visible = this.alpha > 0.001
    this.mat.linewidth = this.width
    this.mat.opacity = Math.min(1, this.width / 3)
    this.line.visible = this.width > 0.05
    return breathing || this.alpha !== target || this.width !== this.look.width
  }
}
