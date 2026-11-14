import {
  BoxGeometry,
  CapsuleGeometry,
  DirectionalLight,
  EdgesGeometry,
  Group,
  HemisphereLight,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  MeshLambertMaterial,
  PlaneGeometry,
  SphereGeometry,
  Vector3,
  type BufferGeometry,
  type Material,
} from 'three'
import type { ObjectMark, Pred, Xray } from './contract'
import { HOME_SPOT, SQUARE_M, nodePosition, zoneAt, zoneCenter } from './frame'
import { OBJECT, PERSON } from './palette'
import { v3 } from './stage'
import { shadowCentre } from './xray'
import type { RoomView } from './view'
import figureUrl from './figures/person-c.glb?url'

// Where the radio thinks the person is: an amber figure in pred.zone, a faint amber tile under each zone in
// zone_set (two figures when the brain can't pick between two zones), and grey-blue box markers for state.objects.
// Nothing is drawn while pred is null.
//
// The figure says only what the radio knows: where (zone and floor point), and moving or still. It is an
// anonymous capsule figure (no face, no hands, no clothes, no gestures). It stands while the person is still and
// walks while they move, facing the way the floor point last travelled. The walk is two shape keys (stepL,
// stepR) in figures/person-c.glb, so it costs one draw call and no skinning. The GLB comes from a script
// (build_c_pill.py), not from hand edits.

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

/** Shortest signed turn from angle a to angle b, in radians. */
export function turn(a: number, b: number): number {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a))
}

const GHOST_ALPHA = 1
const TILE_INSET_M = 0.15
const TILE_ALPHA = 0.09
/** The model is 1.70 m tall; drawn at 1.22 m it stays about 200 px tall on the kiosk and clear of the zone names. */
const FIGURE_SCALE = 0.72
const FIGURE_TOP_M = 1.7
/** Full walk cycles (two steps) per second: an unhurried indoor walk. */
const CYCLE_HZ = 0.85
/** The floor point has to travel this far before the figure turns to face the new way, so jitter can't spin it. */
const HEADING_STEP_M = 0.08

interface Ghost {
  group: Group
  mats: Material[]
  label: HTMLElement
  at: Vector3
  to: Vector3
  alpha: number
  alphaTo: number
  placed: boolean
  /** The figure mesh and its depth-only twin (used while see-through), once the GLB has loaded. */
  body: Mesh | null
  depth: Mesh | null
  keys: [number, number] | null
  /** Where the heading was last taken from, and the heading (radians, 0 = facing the camera). */
  anchor: Vector3
  heading: number
  headingTo: number
  walk: number
  walkTo: number
  phase: number
}

export class Presence {
  /** True while a wave check-in shows: the ghost's label reads "Wave seen". */
  wave = false
  private readonly ghosts: Ghost[] = []
  private readonly tiles: { mesh: Mesh<PlaneGeometry, MeshBasicMaterial>; to: number }[] = []
  private readonly boxes: { mesh: LineSegments; label: HTMLElement }[] = []

  constructor(private readonly view: RoomView) {
    const half = SQUARE_M / 4
    for (let zone = 1; zone <= 4; zone++) {
      const [x, y] = zoneCenter(zone)!
      const mesh = new Mesh(new PlaneGeometry(half * 2, half * 2), new MeshBasicMaterial({ color: PERSON, transparent: true, opacity: 0, depthWrite: false }))
      mesh.rotation.x = -Math.PI / 2
      mesh.position.copy(v3([x, y, 0.001]))
      mesh.renderOrder = -2
      view.scene.add(mesh)
      this.tiles.push({ mesh, to: 0 })
    }

    for (let i = 0; i < 2; i++) {
      const group = new Group()
      group.visible = false
      view.scene.add(group)
      const label = view.addLabel('', new Vector3(), 'room-label--ghost')
      label.hidden = true
      this.ghosts.push({
        group, mats: [], label, at: new Vector3(), to: new Vector3(), alpha: 0, alphaTo: 0, placed: false,
        body: null, depth: null, keys: null, anchor: new Vector3(), heading: 0, headingTo: 0, walk: 0, walkTo: 0, phase: 0,
      })
    }
    // Only the figure is lit; everything else in the room is unlit, so these lights touch nothing else.
    const sky = new HemisphereLight(0xffffff, 0x1a1612, 0.9)
    const key = new DirectionalLight(0xffffff, 2.4)
    key.position.set(-1.2, 3, 2.2)
    view.scene.add(sky, key)
    void this.loadFigure(figureUrl)
    view.addAnimator((dt) => this.ease(dt))
  }

  private async loadFigure(url: string) {
    try {
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js')
      const gltf = await new GLTFLoader().loadAsync(url)
      let source: Mesh | null = null
      gltf.scene.traverse((o) => {
        if (!source && o instanceof Mesh) source = o
      })
      if (!source) throw new Error('no mesh in the figure file')
      const geometry = (source as Mesh).geometry as BufferGeometry
      for (const g of this.ghosts) {
        const mat = new MeshLambertMaterial({ color: PERSON, transparent: true, opacity: g.alpha })
        const body = new Mesh(geometry, mat)
        body.updateMorphTargets()
        body.renderOrder = 11
        // Depth-only twin: while the figure is see-through, it fills the depth first so only the nearest
        // surface takes colour (no arm showing through the chest). Drawn just before the body.
        const depth = new Mesh(geometry, new MeshBasicMaterial({ colorWrite: false }))
        depth.morphTargetInfluences = body.morphTargetInfluences
        depth.renderOrder = 10
        depth.visible = false
        body.scale.setScalar(FIGURE_SCALE)
        depth.scale.setScalar(FIGURE_SCALE)
        // The step names live on the loaded mesh (glTF extras.targetNames), not on the geometry.
        const dict = (source as Mesh).morphTargetDictionary ?? {}
        g.keys = dict.stepL !== undefined && dict.stepR !== undefined ? [dict.stepL, dict.stepR] : null
        g.group.add(depth, body)
        g.body = body
        g.depth = depth
        g.mats = [mat]
      }
      this.view.host.dataset.figure = 'loaded'
    } catch (err) {
      console.warn('figure: could not load, drawing the capsule instead.', err)
      this.useCapsule()
    }
    this.view.requestRender()
  }

  /** The old ghost: a capsule and a head. Used when the figure file can't be loaded. */
  private useCapsule() {
    const body = new CapsuleGeometry(0.12, 0.62, 4, 12)
    const head = new SphereGeometry(0.1, 16, 12)
    for (const g of this.ghosts) {
      const mats = [0, 1].map(() => new MeshBasicMaterial({ color: PERSON, transparent: true, opacity: 0.85 * g.alpha, depthWrite: false }))
      const b = new Mesh(body, mats[0])
      b.position.y = 0.43
      const h = new Mesh(head, mats[1])
      h.position.y = 0.98
      g.group.add(b, h)
      g.mats = mats
    }
    this.view.host.dataset.figure = 'capsule'
  }

  update(pred: Pred | null, objects: ObjectMark[], xray: Xray | null = null, router: string = HOME_SPOT) {
    const shadow = shadowCentre(xray)
    const spots = ghostSpots(pred)
    this.ghosts.forEach((g, i) => {
      const spot = spots[i]
      g.alphaTo = spot ? GHOST_ALPHA * spot.weight : 0
      if (!spot) return
      const [x, y] = spots.length === 1 ? ghostFloor(spot.zone, shadow) : zoneCenter(spot.zone)!
      g.to.copy(v3([x, y, 0]))
      if (!g.placed) {
        g.at.copy(g.to) // the first sighting appears in place; later ones glide
        g.anchor.copy(g.to)
      }
      g.placed = true
      // Face the way the floor point has travelled; hold the last heading while it stays put.
      const dx = g.to.x - g.anchor.x
      const dz = g.to.z - g.anchor.z
      if (spots.length > 1) g.anchor.copy(g.to) // two-zone guesses jump between zone centres: not a walk
      else if (Math.hypot(dx, dz) > HEADING_STEP_M) {
        g.headingTo = Math.atan2(dx, dz)
        g.anchor.copy(g.to)
      }
      g.walkTo = spots.length === 1 && pred!.motion === 'moving' ? 1 : 0
      const waving = this.wave && spots.length === 1
      g.label.textContent = waving ? 'Wave seen' : spots.length > 1 ? `zone ${spot.zone}?` : pred!.motion === 'still' ? 'still' : 'moving'
      g.label.classList.toggle('room-label--wave', waving)
    })
    if (!spots.length) for (const g of this.ghosts) g.placed = false
    const inSet = new Set(spots.map((s) => s.zone))
    this.tiles.forEach((t, i) => (t.to = inSet.has(i + 1) ? TILE_ALPHA : 0))
    this.placeObjects(objects, router)
    this.view.host.dataset.ghost = spots.map((s) => s.zone).join(',')
    const lone = spots.length === 1 ? ghostFloor(spots[0].zone, shadow) : null
    this.view.host.dataset.ghostXy = lone ? `${lone[0].toFixed(2)},${lone[1].toFixed(2)}` : ''
    this.view.requestRender()
  }

  private placeObjects(objects: ObjectMark[], router: string) {
    while (this.boxes.length < objects.length) {
      const mesh = new LineSegments(new EdgesGeometry(new BoxGeometry(0.16, 0.16, 0.16)), new LineBasicMaterial({ color: OBJECT }))
      this.view.scene.add(mesh)
      this.boxes.push({ mesh, label: this.view.addLabel('object', new Vector3(), 'room-label--object') })
    }
    this.boxes.forEach((b, i) => {
      const o = objects[i]
      b.mesh.visible = !!o
      b.label.hidden = !o
      if (!o) return
      b.mesh.position.copy(v3([o.xy_m[0], o.xy_m[1], 0.08]))
      // The tag sits 0.3 m from the object on the side away from the router, so it never lands on the router
      // or its name (the router moves west on advice), and 0.15 m north, clear of the south zone names.
      const east = nodePosition('pi5', router)[0] < o.xy_m[0]
      b.label.classList.toggle('room-label--object-east', east)
      this.view.moveLabel(b.label, v3([o.xy_m[0] + (east ? 0.3 : -0.3), o.xy_m[1] + 0.15, 0.08]))
    })
    this.view.host.dataset.objects = String(objects.length)
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 220)
    const kTurn = 1 - Math.exp(-dt / 160)
    let busy = false
    for (const g of this.ghosts) {
      g.at.lerp(g.to, k)
      g.alpha += (g.alphaTo - g.alpha) * k
      if (Math.abs(g.alphaTo - g.alpha) < 0.004) g.alpha = g.alphaTo
      busy ||= g.alpha !== g.alphaTo || g.at.distanceTo(g.to) > 0.002
      g.group.position.copy(g.at)
      g.group.visible = g.alpha > 0
      const scale = g.body ? 1 : 0.85
      for (const m of g.mats) (m as MeshBasicMaterial).opacity = g.alpha * scale
      if (g.depth) g.depth.visible = g.group.visible && g.alpha < 0.999

      // Turn toward the heading.
      const d = turn(g.heading, g.headingTo)
      g.heading = Math.abs(d) < 0.002 ? g.headingTo : g.heading + d * kTurn
      busy ||= g.heading !== g.headingTo
      g.group.rotation.y = g.body ? g.heading : 0

      // Walk: stand -> stepL -> stand -> stepR, eased in and out so a stop always settles on the standing pose.
      g.walk += (g.walkTo - g.walk) * k
      if (Math.abs(g.walkTo - g.walk) < 0.004) g.walk = g.walkTo
      if (g.walk > 0) g.phase = (g.phase + (dt / 1000) * CYCLE_HZ * 2 * Math.PI) % (2 * Math.PI)
      if (g.body?.morphTargetInfluences && g.keys) {
        const s = Math.sin(g.phase)
        g.body.morphTargetInfluences[g.keys[0]] = g.walk * Math.max(0, s)
        g.body.morphTargetInfluences[g.keys[1]] = g.walk * Math.max(0, -s)
      }
      busy ||= g.group.visible && (g.walk > 0 || g.walkTo > 0)

      g.label.hidden = g.alphaTo === 0
      const top = g.body ? FIGURE_TOP_M * FIGURE_SCALE + 0.1 : 1.18
      if (!g.label.hidden) this.view.moveLabel(g.label, g.at.clone().setY(top))
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
