import {
  BoxGeometry,
  CapsuleGeometry,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  SphereGeometry,
  Vector3,
} from 'three'
import type { ObjectMark, Pred, Xray } from './contract'
import { SQUARE_M, zoneAt, zoneCenter } from './frame'
import { INK, OLIVE } from './palette'
import { v3 } from './stage'
import { shadowCentre } from './xray'
import type { RoomView } from './view'

// Where the radio thinks the person is: an olive ghost in pred.zone, a faint olive tile under each zone in
// zone_set (two ghosts when the brain can't pick between two zones), and ink box markers for state.objects.
// Nothing is drawn while pred is null.

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
  const half = SQUARE_M / 4 - TILE_INSET_M
  const clamp = (v: number, c: number) => Math.min(c + half, Math.max(c - half, v))
  return [clamp(shadow[0], centre[0]), clamp(shadow[1], centre[1])]
}

const GHOST_ALPHA = 0.85
const TILE_INSET_M = 0.15
const TILE_ALPHA = 0.09

interface Ghost {
  group: Group
  mats: MeshBasicMaterial[]
  label: HTMLElement
  at: Vector3
  to: Vector3
  alpha: number
  alphaTo: number
  placed: boolean
}

export class Presence {
  private readonly ghosts: Ghost[] = []
  private readonly tiles: { mesh: Mesh<PlaneGeometry, MeshBasicMaterial>; to: number }[] = []
  private readonly boxes: { mesh: LineSegments; label: HTMLElement }[] = []

  constructor(private readonly view: RoomView) {
    const half = SQUARE_M / 4
    for (let zone = 1; zone <= 4; zone++) {
      const [x, y] = zoneCenter(zone)!
      const mesh = new Mesh(new PlaneGeometry(half * 2, half * 2), new MeshBasicMaterial({ color: OLIVE, transparent: true, opacity: 0, depthWrite: false }))
      mesh.rotation.x = -Math.PI / 2
      mesh.position.copy(v3([x, y, 0.001]))
      mesh.renderOrder = -2
      view.scene.add(mesh)
      this.tiles.push({ mesh, to: 0 })
    }

    const body = new CapsuleGeometry(0.12, 0.62, 4, 12)
    const head = new SphereGeometry(0.1, 16, 12)
    for (let i = 0; i < 2; i++) {
      const mats = [0, 1].map(() => new MeshBasicMaterial({ color: OLIVE, transparent: true, opacity: 0, depthWrite: false }))
      const group = new Group()
      const b = new Mesh(body, mats[0])
      b.position.y = 0.43
      const h = new Mesh(head, mats[1])
      h.position.y = 0.98
      group.add(b, h)
      group.visible = false
      view.scene.add(group)
      const label = view.addLabel('', new Vector3(), 'room-label--ghost')
      label.hidden = true
      this.ghosts.push({ group, mats, label, at: new Vector3(), to: new Vector3(), alpha: 0, alphaTo: 0, placed: false })
    }
    view.addAnimator((dt) => this.ease(dt))
  }

  update(pred: Pred | null, objects: ObjectMark[], xray: Xray | null = null) {
    const shadow = shadowCentre(xray)
    const spots = ghostSpots(pred)
    this.ghosts.forEach((g, i) => {
      const spot = spots[i]
      g.alphaTo = spot ? GHOST_ALPHA * spot.weight : 0
      if (!spot) return
      const [x, y] = spots.length === 1 ? ghostFloor(spot.zone, shadow) : zoneCenter(spot.zone)!
      g.to.copy(v3([x, y, 0]))
      if (!g.placed) g.at.copy(g.to) // the first sighting appears in place; later ones glide
      g.placed = true
      g.label.textContent = spots.length > 1 ? `zone ${spot.zone}?` : pred!.motion === 'still' ? 'still' : 'moving'
    })
    if (!spots.length) for (const g of this.ghosts) g.placed = false
    const inSet = new Set(spots.map((s) => s.zone))
    this.tiles.forEach((t, i) => (t.to = inSet.has(i + 1) ? TILE_ALPHA : 0))
    this.placeObjects(objects)
    this.view.host.dataset.ghost = spots.map((s) => s.zone).join(',')
    const lone = spots.length === 1 ? ghostFloor(spots[0].zone, shadow) : null
    this.view.host.dataset.ghostXy = lone ? `${lone[0].toFixed(2)},${lone[1].toFixed(2)}` : ''
    this.view.requestRender()
  }

  private placeObjects(objects: ObjectMark[]) {
    while (this.boxes.length < objects.length) {
      const mesh = new LineSegments(new EdgesGeometry(new BoxGeometry(0.16, 0.16, 0.16)), new LineBasicMaterial({ color: INK }))
      this.view.scene.add(mesh)
      this.boxes.push({ mesh, label: this.view.addLabel('object', new Vector3(), 'room-label--object') })
    }
    this.boxes.forEach((b, i) => {
      const o = objects[i]
      b.mesh.visible = !!o
      b.label.hidden = !o
      if (!o) return
      b.mesh.position.copy(v3([o.xy_m[0], o.xy_m[1], 0.08]))
      // The tag ends 0.3 m west of the object, so it never sits on the router or the router's name, and
      // 0.15 m north of it, so an object by the router (the tray, T1) doesn't put it on the zone 3 name.
      this.view.moveLabel(b.label, v3([o.xy_m[0] - 0.3, o.xy_m[1] + 0.15, 0.08]))
    })
    this.view.host.dataset.objects = String(objects.length)
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 220)
    let busy = false
    for (const g of this.ghosts) {
      g.at.lerp(g.to, k)
      g.alpha += (g.alphaTo - g.alpha) * k
      if (Math.abs(g.alphaTo - g.alpha) < 0.004) g.alpha = g.alphaTo
      busy ||= g.alpha !== g.alphaTo || g.at.distanceTo(g.to) > 0.002
      g.group.position.copy(g.at)
      g.group.visible = g.alpha > 0
      for (const m of g.mats) m.opacity = g.alpha
      g.label.hidden = g.alphaTo === 0
      if (!g.label.hidden) this.view.moveLabel(g.label, g.at.clone().setY(1.18))
    }
    for (const t of this.tiles) {
      const m = t.mesh.material
      m.opacity += (t.to - m.opacity) * k
      if (Math.abs(t.to - m.opacity) < 0.002) m.opacity = t.to
      busy ||= m.opacity !== t.to
      t.mesh.visible = m.opacity > 0
    }
    return busy
  }
}
