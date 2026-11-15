import {
  BoxGeometry,
  DirectionalLight,
  EdgesGeometry,
  HemisphereLight,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  Vector3,
} from 'three'
import type { ObjectMark, Pred, Xray } from './contract'
import { createFigure, FIGURE_HEIGHT_M, type Figure } from './figure'
import { EASE_CSS, fade, GHOST_OMEGA, Held, MOTION, springStep } from './motion'
import { SIZE_M, ZONES, floorSize, toScene, zoneAt, zoneCenter, zoneRect } from './frame'
import { OBJECT, PERSON } from './palette'
import { standBase, v3 } from './stage'
import { shadowCentre } from './xray'
import type { RoomView } from './view'

// Where the radio thinks the person is: one amber figure, a faint amber tile under each zone in zone_set (the
// figure stands toward the line when the brain can't pick between two zones), and grey-blue box markers for
// state.objects. Nothing is drawn while pred is null.
//
// Motion (AGENTS.md Style, motion.ts): the figure moves only once a new zone has held for 200 ms, then glides on
// a critically damped spring (about 650 ms, no overshoot). Its words cross-fade; nothing teleports.
//
// The figure says only what the radio knows: where (zone and floor point), and moving or still. It is a simple,
// faceless figure (figure.ts) that stands while the person is still and walks while they move, facing the way it
// glides.

export interface GhostSpot {
  zone: number
  /** 0..1, how solid this ghost is drawn. */
  weight: number
}

/** The ghosts to draw for a prediction: one per zone in zone_set, weighted by probability. */
export function ghostSpots(pred: Pred | null): GhostSpot[] {
  if (!pred || !pred.present || pred.kind !== 'person') return []
  const zones = (pred.zone_set?.length ? pred.zone_set : [pred.zone]).filter((z) => zoneCenter(z)).slice(0, 2)
  if (zones.length < 2) return zones.map((zone) => ({ zone, weight: 1 }))
  const p = zones.map((z) => pred.probs?.[z] ?? 0)
  const top = Math.max(...p)
  return zones.map((zone, i) => ({ zone, weight: top > 0 ? Math.max(0.35, p[i] / top) * 0.6 : 0.5 }))
}

/**
 * Where a lone ghost stands: on the person's radio shadow when that lies inside the zone's tile (kept 0.15 m
 * in from its edges), so one person never shows up in two places; otherwise in the middle of the zone.
 */
export function ghostFloor(zone: number, shadow: [number, number] | null): [number, number] {
  const centre = zoneCenter(zone)!
  if (!shadow || zoneAt(shadow[0], shadow[1]) !== zone) return centre
  const [x0, y0, x1, y1] = zoneRect(zone)!
  const clamp = (v: number, lo: number, hi: number) => Math.min(hi - TILE_INSET_M, Math.max(lo + TILE_INSET_M, v))
  return [clamp(shadow[0], x0, x1), clamp(shadow[1], y0, y1)]
}

/**
 * Where the one figure stands. Sure of one zone: on the person's shadow inside it (ghostFloor). Unsure between
 * two: between the two zone centres, weighted by probability, so it stands toward the line between them instead
 * of splitting into two figures.
 */
export function ghostTarget(zones: number[], probs: number[] | undefined, shadow: [number, number] | null): [number, number] | null {
  if (zones.length === 1) return zoneCenter(zones[0]) ? ghostFloor(zones[0], shadow) : null
  let x = 0
  let y = 0
  let w = 0
  for (const z of zones) {
    const c = zoneCenter(z)
    if (!c) continue
    const p = Math.max(0.05, probs?.[z] ?? 1)
    x += p * c[0]
    y += p * c[1]
    w += p
  }
  return w > 0 ? [x / w, y / w] : null
}

const TILE_INSET_M = 0.15
const TILE_ALPHA = 0.09
/** A new zone set must hold this long (3 decisions in a row) before the figure heads for it. */
const ZONE_HOLD_MS = 200
/** "still" / "moving" must hold this long (5 decisions) before the figure and its label change. */
const MOTION_HOLD_MS = 400
/** The figure turns to face its glide only above this speed, so drifting in place can't spin it. */
const TURN_SPEED_MPS = 0.12

const zonesKey = (spots: GhostSpot[]) => spots.map((s) => s.zone).sort().join(',')

/**
 * Where an object's tag goes: centred 0.3 m north of it, or 0.3 m south when that would reach the north zone
 * names. Zone names fill the square's outer rows and the router's name sits level with its head (about 0.8 m
 * into the square, as seen from the camera), so this lane between them stays clear on any canvas size.
 */
export function objectTagAt([x, y]: [number, number]): [number, number, number] {
  return [x, y + 0.3 <= SIZE_M[1] - 0.45 ? y + 0.3 : y - 0.3, standBase([x, y, 0])[2] + 0.08]
}

export class Presence {
  /** True while a wave check-in shows: the figure's label reads "Wave seen". */
  wave = false
  private readonly figure: Figure
  private readonly label: HTMLElement
  /** The label's words, in their own span so they can cross-fade while the label fades with the figure. */
  private readonly labelWords: HTMLElement
  private labelText = ''
  private readonly at = new Vector3()
  private readonly vel = new Vector3()
  /** Walking (one zone, moving) or standing, as the held motion says. */
  private walking = false
  private readonly to = new Vector3()
  private alpha = 0
  private alphaTo = 0
  private placed = false
  private readonly zones = new Held<string>('', ZONE_HOLD_MS)
  private readonly motion = new Held<string>('', MOTION_HOLD_MS)
  private probs: number[] | undefined
  private readonly tiles: { zone: number; mesh: Mesh<PlaneGeometry, MeshBasicMaterial>; to: number }[] = []
  private readonly boxes: { mesh: LineSegments<EdgesGeometry, LineBasicMaterial>; label: HTMLElement; to: number }[] = []

  constructor(private readonly view: RoomView) {
    for (const { id: zone } of ZONES) {
      const [x0, y0, x1, y1] = zoneRect(zone)!
      const mesh = new Mesh(new PlaneGeometry(x1 - x0, y1 - y0), new MeshBasicMaterial({ color: PERSON, transparent: true, opacity: 0, depthWrite: false }))
      mesh.rotation.x = -Math.PI / 2
      mesh.position.copy(v3([(x0 + x1) / 2, (y0 + y1) / 2, 0.001]))
      mesh.renderOrder = -2
      view.scene.add(mesh)
      this.tiles.push({ zone, mesh, to: 0 })
    }

    // One figure only: two half-strength figures read as two people from across the room.
    this.figure = createFigure((loaded) => {
      this.view.host.dataset.figure = loaded ? 'loaded' : 'capsule'
      this.view.requestRender()
    })
    this.figure.object.visible = false
    view.scene.add(this.figure.object)
    this.label = view.addLabel('', new Vector3(), 'room-label--ghost')
    this.label.style.opacity = '0'
    this.labelWords = document.createElement('span')
    this.label.append(this.labelWords)
    // Only the figure is lit; everything else in the room is unlit, so these lights touch nothing else.
    const sky = new HemisphereLight(0xffffff, 0x1a1612, 0.9)
    const key = new DirectionalLight(0xffffff, 2.4)
    key.position.set(-1.2, 3, 2.2)
    view.scene.add(sky, key)
    view.addAnimator((dt) => this.ease(dt))
  }

  /** Where the figure stands now (scene floor point) and how visible it is (0..1), for the hall view's column. */
  standing(): { at: Vector3; alpha: number } {
    return { at: this.at, alpha: this.alpha }
  }

  /** The zones the screen shows right now (held), for the zone names and tiles. */
  shownZones(): number[] {
    return this.placed && this.zones.value ? this.zones.value.split(',').map(Number) : []
  }

  update(pred: Pred | null, objects: ObjectMark[], xray: Xray | null = null, nowMs = performance.now()) {
    const spots = ghostSpots(pred)
    let lone: [number, number] | null = null
    if (!spots.length) {
      // Gone: fade out where it stands. The next sighting starts fresh, in place.
      this.alphaTo = 0
      this.placed = false
      this.zones.set('')
      this.motion.set('')
      this.walking = false
    } else {
      const key = zonesKey(spots)
      if (!this.placed) {
        this.zones.set(key)
        this.motion.set(pred!.motion ?? 'still')
      }
      if (this.zones.update(key, nowMs) === key) this.probs = pred!.probs
      const zones = this.zones.value.split(',').map(Number)
      const target = ghostTarget(zones, this.probs, shadowCentre(xray))!
      if (zones.length === 1) lone = target
      this.to.copy(v3([target[0], target[1], 0]))
      if (!this.placed) {
        this.at.copy(this.to) // the first sighting appears in place; later ones glide
        this.vel.set(0, 0, 0)
        this.placed = true
      }
      this.alphaTo = 1
      const motion = this.motion.update(pred!.motion ?? 'still', nowMs)
      this.walking = zones.length === 1 && motion === 'moving' // the pace is set every frame in ease()
      // Very little text (AGENTS.md Style): the walk already shows moving or still, and the lit zone names and
      // tiles show which zones the radio is weighing. The figure only speaks for the check-in, because green
      // always comes with a word.
      const waving = this.wave && zones.length === 1
      this.say(waving ? 'Wave seen' : '')
      this.label.classList.toggle('room-label--wave', waving)
    }
    const lit = new Set(this.shownZones())
    for (const t of this.tiles) t.to = lit.has(t.zone) ? TILE_ALPHA : 0
    this.placeObjects(objects)
    this.view.host.dataset.ghost = this.shownZones().join(',')
    this.view.host.dataset.ghostXy = lone ? `${lone[0].toFixed(2)},${lone[1].toFixed(2)}` : ''
    this.view.requestRender()
  }

  /** Changes the label's words the way every text on screen changes: out in 100 ms, then in over 140 ms. */
  private say(text: string) {
    if (text === this.labelText) return
    const first = !this.labelText
    this.labelText = text
    const span = this.labelWords
    if (first || typeof span.animate !== 'function') {
      span.textContent = text
      return
    }
    for (const a of span.getAnimations()) a.cancel()
    const out = span.animate([{ opacity: 1 }, { opacity: 0 }], { duration: MOTION.out, easing: EASE_CSS, fill: 'forwards' })
    out.onfinish = () => {
      span.textContent = this.labelText
      out.cancel()
      span.animate([{ opacity: 0 }, { opacity: 1 }], { duration: MOTION.in, easing: EASE_CSS })
    }
  }

  private placeObjects(objects: ObjectMark[]) {
    while (this.boxes.length < objects.length) {
      const mesh = new LineSegments(new EdgesGeometry(new BoxGeometry(0.16, 0.16, 0.16)), new LineBasicMaterial({ color: OBJECT, transparent: true, opacity: 0 }))
      mesh.visible = false
      this.view.scene.add(mesh)
      const label = this.view.addLabel('object', new Vector3(), 'room-label--object')
      label.style.opacity = '0'
      this.boxes.push({ mesh, label, to: 0 })
    }
    this.boxes.forEach((b, i) => {
      const o = objects[i]
      b.to = o ? 1 : 0
      if (!o) return
      // On the desk top for the tray on the desk (the dead-zone beat), on the floor anywhere else.
      b.mesh.position.copy(v3([o.xy_m[0], o.xy_m[1], standBase([o.xy_m[0], o.xy_m[1], 0])[2] + 0.08]))
      this.view.moveLabel(b.label, v3(objectTagAt(o.xy_m)))
    })
    this.view.host.dataset.objects = String(objects.length)
  }

  private ease(dt: number): boolean {
    let busy = false

    // Position: a critically damped spring per floor axis (about 650 ms, no overshoot), so 10 Hz steps and a
    // noisy shadow centre become one smooth walk.
    ;[this.at.x, this.vel.x] = springStep(this.at.x, this.vel.x, this.to.x, GHOST_OMEGA, dt)
    ;[this.at.z, this.vel.z] = springStep(this.at.z, this.vel.z, this.to.z, GHOST_OMEGA, dt)
    busy ||= this.at.distanceTo(this.to) > 0.002 || this.vel.length() > 0.002
    // Face the way the figure is gliding; hold the heading while it stands. The walk takes the glide's speed, so
    // its stride and cadence match how fast the floor point travels and the planted foot doesn't slide.
    const speed = Math.hypot(this.vel.x, this.vel.z)
    if (speed > TURN_SPEED_MPS) this.figure.setHeading(Math.atan2(this.vel.x, this.vel.z))
    this.figure.setMoving(this.walking, speed)

    this.alpha = fade(this.alpha, this.alphaTo, dt)
    busy ||= this.alpha !== this.alphaTo
    this.figure.object.position.copy(this.at)
    this.figure.object.scale.setScalar(0.94 + 0.06 * this.alpha) // arrives with a small settle, leaves the same way
    this.figure.object.visible = this.alpha > 0
    this.figure.setOpacity(this.alpha)
    // Called every frame: inside `busy ||= ...` it was skipped whenever the glide was busy, freezing the walk.
    const figureBusy = this.figure.update(dt)
    busy ||= figureBusy && this.figure.object.visible
    // The label fades with the figure rather than popping in at full strength.
    this.label.style.opacity = this.alpha.toFixed(3)
    this.label.hidden = this.alpha === 0 || !this.labelText
    if (!this.label.hidden) {
      // Beside the chest, not over the head, so it never reaches up into a zone name. It goes on the east side
      // unless the figure is near the east edge, then on the west.
      const west = this.at.x > toScene([floorSize()[0], 0, 0])[0] - 0.35
      this.label.classList.toggle('room-label--ghost-west', west)
      this.view.moveLabel(this.label, this.at.clone().set(this.at.x + (west ? -0.2 : 0.2), FIGURE_HEIGHT_M * 0.62, this.at.z))
    }

    for (const t of this.tiles) {
      const m = t.mesh.material
      m.opacity = fade(m.opacity, t.to, dt)
      busy ||= m.opacity !== t.to
      t.mesh.visible = m.opacity > 0
    }
    for (const b of this.boxes) {
      const m = b.mesh.material
      m.opacity = fade(m.opacity, b.to, dt)
      busy ||= m.opacity !== b.to
      b.mesh.visible = m.opacity > 0
      b.label.style.opacity = m.opacity.toFixed(3)
      b.label.hidden = m.opacity === 0
    }
    return busy
  }
}
