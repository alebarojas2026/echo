import {
  BoxGeometry,
  BufferGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  Mesh,
  MeshBasicMaterial,
  PlaneGeometry,
  Vector3,
} from 'three'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js'
import { HOME_SPOT, NODES, SIZE_M, STRIP_M, ZONES, ZONE_SPLIT_X_M, alertWordAt, deskEdge, floorSize, nodeLabelSide, nodePosition, routerId, toScene, zoneRect, zoneSide, zoneWords, type NodeId, type Vec3 } from './frame'
import type { Hearing } from './heard'
import { fade, Glide3 } from './motion'
import { EDGE, FAULT, FLOOR, SQUARE, TEXT, WALL_SHADE } from './palette'
import { at, mix, shadedGeometry, type Part } from './shade'
import type { RoomView } from './view'

// The still parts of the room as a scale model: a floor plinth with low walls on three sides, the 2 x 2 m
// square and its zones, and the four nodes. The plinth, walls and lines are baked-shaded MeshBasicMaterial
// (vertex colours from one fixed light, shade.ts), so the Pi draws a shaded room for the price of a flat one.

const MARGIN_M = 0.32 // plinth beyond the square on the west, north and east
const SOUTH_M = 0.46 // and on the south, where the router spots and the X-ray caption sit
const WALL_M = 0.3 // low walls edge the floor without hiding it
const WALL_T_M = 0.04
const PLINTH_M = 0.09 // the slab the model stands on
const SHADOW_M = 0.05 // how far the slab's hard shadow falls to the south-east

export function v3(p: Vec3): Vector3 {
  const [x, y, z] = toScene(p)
  return new Vector3(x, y, z)
}

export function segments(pairs: Vec3[], material: LineBasicMaterial | LineDashedMaterial): LineSegments {
  const pos: number[] = []
  for (const p of pairs) pos.push(...toScene(p))
  const geom = new BufferGeometry()
  geom.setAttribute('position', new Float32BufferAttribute(pos, 3))
  const lines = new LineSegments(geom, material)
  if (material instanceof LineDashedMaterial) lines.computeLineDistances()
  return lines
}

/** The desk's top, metres above the floor (CONTRACTS.md section 3: every antenna is 1 m up, a 25 cm box on it). */
export const DESK_TOP_M = 0.75

/** The plinth, low walls and slab shadow (replaced by a room scan when there is one), the floor area with its
 *  zone lines, and on the desk layout the desk top behind the strip. */
function buildShell(): { room: Group; square: Group } {
  const g = new Group()
  const sq = new Group()
  const west = -MARGIN_M
  const east = SIZE_M[0] + MARGIN_M
  const north = SIZE_M[1] + MARGIN_M
  const south = -SOUTH_M
  const sizeX = east - west
  const sizeY = north - south
  const [cx, , cz] = toScene([(west + east) / 2, (south + north) / 2, 0])

  // The slab: floor-coloured top, its sides falling off toward the wall shade, a hard shadow under it.
  const slab = shadedGeometry([
    { geom: new BoxGeometry(sizeX, PLINTH_M, sizeY), light: FLOOR, dark: mix(FLOOR, WALL_SHADE, 0.7), at: at(cx, -PLINTH_M / 2, cz) },
  ])
  const shadow = new Mesh(new PlaneGeometry(sizeX, sizeY), new MeshBasicMaterial({ color: WALL_SHADE }))
  shadow.rotation.x = -Math.PI / 2
  shadow.position.set(cx + SHADOW_M, -PLINTH_M - 0.002, cz + SHADOW_M * 1.4)
  g.add(shadow, new Mesh(slab, new MeshBasicMaterial({ vertexColors: true })))

  // Low walls on the west, north and east, their cut tops drawn in the edge colour like a section.
  const t = WALL_T_M
  const h = WALL_M
  const walls: Part[] = []
  const wall = (w: number, d: number, x: number, z: number) => {
    walls.push({ geom: new BoxGeometry(w, h, d), light: mix(FLOOR, EDGE, 0.35), dark: mix(FLOOR, WALL_SHADE, 0.6), at: at(x, h / 2, z) })
    walls.push({ geom: new PlaneGeometry(w, d), light: EDGE, dark: EDGE, at: at(x, h + 0.001, z, -Math.PI / 2) })
  }
  const [nx, , nz] = toScene([(west + east) / 2, north - t / 2, 0])
  wall(sizeX, t, nx, nz)
  const sideLen = sizeY - t
  const [wx, , wz] = toScene([west + t / 2, south + sideLen / 2, 0])
  wall(t, sideLen, wx, wz)
  const [ex, , ez] = toScene([east - t / 2, south + sideLen / 2, 0])
  wall(t, sideLen, ex, ez)
  g.add(new Mesh(shadedGeometry(walls), new MeshBasicMaterial({ vertexColors: true })))

  // The floor area (the square, or the strip) and its zone lines as thin strips, so they hold up at 0.85 render
  // scale and 3 m.
  const [fw, fh] = floorSize()
  const lines: Part[] = []
  const strip = (a: Vec3, b: Vec3, wide: number, color: number) => {
    const [ax, , az] = toScene(a)
    const [bx, , bz] = toScene(b)
    const len = Math.hypot(bx - ax, bz - az)
    const ang = Math.atan2(-(bz - az), bx - ax)
    lines.push({ geom: new PlaneGeometry(len + wide, wide), light: color, dark: color, at: at((ax + bx) / 2, 0.001, (az + bz) / 2, -Math.PI / 2, ang) })
  }
  const edges: [Vec3, Vec3][] = [
    [[0, 0, 0], [fw, 0, 0]],
    [[fw, 0, 0], [fw, fh, 0]],
    [[fw, fh, 0], [0, fh, 0]],
    [[0, fh, 0], [0, 0, 0]],
  ]
  for (const [a, b] of edges) strip(a, b, 0.014, SQUARE)
  if (STRIP_M) {
    // One line between the strip's two zones; none across a strip that is one spot.
    if (ZONE_SPLIT_X_M !== null) strip([ZONE_SPLIT_X_M, 0, 0], [ZONE_SPLIT_X_M, fh, 0], 0.007, EDGE)
  } else {
    strip([fw / 2, 0, 0], [fw / 2, fh, 0], 0.007, EDGE)
    strip([0, fh / 2, 0], [fw, fh / 2, 0], 0.007, EDGE)
  }
  sq.add(new Mesh(shadedGeometry(lines), new MeshBasicMaterial({ vertexColors: true })))

  // The desk behind the strip: a plain top from its edge (deskEdge) to the layout's back, at desk height.
  const edge = deskEdge()
  if (edge !== null && SIZE_M[1] > edge) {
    const depth = SIZE_M[1] - edge
    const [dx, , dz] = toScene([SIZE_M[0] / 2, edge + depth / 2, 0])
    const top: Part = { geom: new BoxGeometry(SIZE_M[0], 0.03, depth), light: mix(FLOOR, EDGE, 0.5), dark: mix(FLOOR, WALL_SHADE, 0.6), at: at(dx, DESK_TOP_M - 0.015, dz) }
    // With the drawn floor and walls: a loaded hall has its own desk, and our devices stand on that one.
    g.add(new Mesh(shadedGeometry([top]), new MeshBasicMaterial({ vertexColors: true })))
  }
  return { room: g, square: sq }
}

/** Segment pairs that join the points in order and close the loop. */
function outline(pts: Vec3[]): Vec3[] {
  return pts.flatMap((p, i) => [p, pts[(i + 1) % pts.length]])
}

const HEAD_M = 0.08
const ZONE_IN_X = 0.1 // zone names start (west zones) or end (east zones) this far in from the side

/** Where a node's stand meets something: the desk top for a device on the desk, else the floor. (An arm out from
 *  the desk's edge read as a stray line from the camera's side; a post to the floor reads as a stand.) */
export function standBase([x, y]: Vec3): Vec3 {
  const edge = deskEdge()
  return edge !== null && y >= edge - 0.01 ? [x, y, DESK_TOP_M] : [x, y, 0]
}

const CHAIR_SEAT_M = 0.45
const CHAIR_BACK_M = 0.85
const CHAIR_W_M = 0.42
/** Higher off the ground than this, a device is on a stand (a post), not on something put on a chair. */
const CHAIR_MAX_M = 1.1

/**
 * Whether a device stands on a chair: across the spot from the desk (south of the floor a person stands on,
 * where nobody stands), and as far above what is under it (`base`, from standBase or standOn) as a chair with
 * something on its seat holds a device. A device on a desk, or on a post at the strip's end, is not.
 */
export function onChair(p: Vec3, base: Vec3): boolean {
  const up = p[2] - base[2]
  return STRIP_M !== null && p[1] < -0.01 && up >= CHAIR_SEAT_M && up <= CHAIR_MAX_M
}

/** A plain chair facing the desk, its back to the south, with a box on its seat that raises the device to `up`
 *  metres above the ground. Scene units, the ground under the device at the origin. */
export function chairGeometry(up: number): BufferGeometry {
  const light = mix(EDGE, SQUARE, 0.35)
  const dark = mix(FLOOR, EDGE, 0.7)
  const leg = CHAIR_W_M / 2 - 0.02
  const parts: Part[] = [
    { geom: new BoxGeometry(CHAIR_W_M, 0.04, CHAIR_W_M), light, dark, at: at(0, CHAIR_SEAT_M - 0.02, 0) },
    { geom: new BoxGeometry(CHAIR_W_M, CHAIR_BACK_M - CHAIR_SEAT_M, 0.04), light, dark, at: at(0, (CHAIR_BACK_M + CHAIR_SEAT_M) / 2, leg) },
    ...[[-leg, -leg], [leg, -leg], [-leg, leg], [leg, leg]].map(([x, z]) => ({ geom: new BoxGeometry(0.03, CHAIR_SEAT_M - 0.04, 0.03), light, dark, at: at(x, (CHAIR_SEAT_M - 0.04) / 2, z) })),
  ]
  const rise = up - HEAD_M / 2 - CHAIR_SEAT_M
  if (rise > 0.01) parts.push({ geom: new BoxGeometry(0.24, rise, 0.24), light, dark, at: at(0, CHAIR_SEAT_M + rise / 2, 0) })
  return shadedGeometry(parts)
}

/** How far around its middle a device rests on things: its stand runs to the highest surface within this of it,
 *  so a device on a desk's very edge stands on the desk, not on the floor beside it. */
const FOOT_M = 0.05

/**
 * Where a device's stand starts when a model of the room says what is under it (the hall): on the highest thing
 * within its footprint at or below it (our desk, the next row's desk, a chair), else on the floor under it,
 * free-standing. `under(x, y, z)` is the model's surface height (contract z) under a contract point, or null.
 * Whatever nodes.json says, a device is drawn where it is; nothing assumes it is on our desk.
 */
export function standOn([x, y, z]: Vec3, under: (x: number, y: number, z: number) => number | null): Vec3 {
  let top: number | null = null
  for (const [dx, dy] of [[0, 0], [FOOT_M, 0], [-FOOT_M, 0], [0, FOOT_M], [0, -FOOT_M]]) {
    const h = under(x + dx, y + dy, z)
    if (h !== null && h <= z && (top === null || h > top)) top = h
  }
  return [x, y, top ?? 0]
}

/** Stands are drawn in the devices' own colour, fainter than the head, and wide enough to read on a desk top. */
const STAND_ALPHA = 0.45
const STAND_PX = 2

interface NodeMesh {
  id: NodeId
  head: Mesh<BoxGeometry, MeshBasicMaterial>
  post: LineSegments2
  label: HTMLElement
  /** 0..1 as drawn, and where it is heading: 1 heard, LOST_ALPHA heard before but quiet now, 0 never heard. */
  alpha: number
  alphaTo: number
  /** The chair under it, when it stands on one (onChair), and how high above the ground that chair holds it. */
  chair: Mesh<BufferGeometry, MeshBasicMaterial> | null
  chairUp: number
}

/** How faint a device that has gone quiet is drawn, beside its name and "not heard". */
const LOST_ALPHA = 0.25

export class Stage {
  readonly group = new Group()
  /** The drawn floor and walls; hidden while a room scan stands in for them. */
  readonly drawnRoom: Group
  private readonly nodes: NodeMesh[] = []
  private readonly zoneLabels = new Map<number, HTMLElement>()
  private readonly routerGlide = new Glide3(nodePosition(routerId(), HOME_SPOT))
  private hearing: ReadonlyMap<string, Hearing> = new Map()
  private tamper = new Set<string>()

  constructor(private readonly view: RoomView) {
    const { room, square } = buildShell()
    this.drawnRoom = room
    this.group.add(room, square)

    // Zone names sit in each zone's outer corner (on the strip, its aisle side), clear of the links that cross
    // the middle. West zones read from their west edge, east zones end at their east edge.
    const inX = ZONE_IN_X
    const inY = 0.2
    for (const z of ZONES) {
      const [x0, y0, x1, y1] = zoneRect(z.id)!
      const { east, north } = zoneSide(z.id)
      // On the desk the person stands in the middle of a zone 0.6 m deep, on top of any name inside it: the name
      // goes just outside the strip on the aisle side, under its zone (where alertWordAt puts the alert's word).
      const at = STRIP_M ? v3(alertWordAt(z.id)[0]) : v3([east ? x1 - inX : x0 + inX, north ? y1 - inY : y0 + inY, 0])
      const side = STRIP_M ? ' room-label--zone-south' : east ? ' room-label--zone-east' : ''
      this.zoneLabels.set(z.id, view.addLabel(zoneWords(z.id), at, `room-label--zone${side}`))
    }

    // Devices are live (heard.ts): each starts unseen and fades in once the board hears it.
    const headGeom = new BoxGeometry(HEAD_M, HEAD_M, HEAD_M)
    for (const info of Object.values(NODES)) {
      const head = new Mesh(headGeom, new MeshBasicMaterial({ color: TEXT, transparent: true, opacity: 0 }))
      const postMat = new LineMaterial({ color: TEXT, linewidth: STAND_PX, transparent: true, opacity: 0 })
      const post = new LineSegments2(new LineSegmentsGeometry(), postMat)
      view.onResize((w, h) => postMat.resolution.set(w, h))
      head.visible = post.visible = false
      this.group.add(head, post)
      const label = view.addLabel(info.name, new Vector3(), `room-label--node room-label--${nodeLabelSide(info.id)}`)
      label.hidden = true
      this.nodes.push({ id: info.id, head, post, label, alpha: 0, alphaTo: 0, chair: null, chairUp: 0 })
    }
    this.putNodes()
    view.addAnimator((dt) => this.fadeNodes(dt))
    view.addAnimator((dt) => {
      const moving = this.routerGlide.step(dt)
      if (moving) this.putNodes()
      return moving
    })
    view.scene.add(this.group)
  }

  /** Puts every node at its spot; the router glides (600 ms) to the spot in state.router. */
  placeNodes(router: string | null | undefined) {
    this.routerGlide.set(nodePosition(routerId(), router))
    this.view.requestRender()
  }

  /** The room model's surface height under a contract point, when there is a model (setGround). */
  private ground: ((x: number, y: number, z: number) => number | null) | null = null

  /** A model of the room is there (or was moved): the stands run to what it really has under each device. */
  setGround(under: ((x: number, y: number, z: number) => number | null) | null) {
    this.ground = under
    this.stood.clear()
    this.putNodes()
  }

  /** Looking down through the model costs a pass over its triangles: once per device and 5 cm spot, not per frame
   *  (the router glides). */
  private readonly stood = new Map<string, Vec3>()

  private standFor(id: string, p: Vec3): Vec3 {
    if (!this.ground) return standBase(p)
    const key = `${id}:${p.map((v) => Math.round(v * 20)).join(',')}`
    let base = this.stood.get(key)
    if (!base) this.stood.set(key, (base = standOn(p, this.ground)))
    return [p[0], p[1], base[2]]
  }

  private putNodes() {
    const router = routerId()
    for (const n of this.nodes) {
      const p = n.id === router ? this.routerGlide.now() : nodePosition(n.id, null)
      const top = v3(p)
      n.head.position.copy(top)
      // Two devices closer than their cubes are wide (the board and Pi A side by side) are drawn smaller, so they
      // read as two.
      const crowded = this.nodes.some((o) => o !== n && Math.hypot(...nodePosition(o.id, null).map((v, i) => v - p[i])) < HEAD_M * 1.5)
      n.head.scale.setScalar(crowded ? 0.7 : 1)
      // The stand: a post up to the head from what is under it in the room's model, else from the drawn desk top
      // or the floor.
      const base = this.standFor(n.id, p)
      // A device across the spot at about desk height is on a chair, with a box on the seat under it.
      const up = onChair(p, base) ? Math.round((p[2] - base[2]) * 100) / 100 : 0
      if (up !== n.chairUp) {
        if (n.chair) {
          this.group.remove(n.chair)
          n.chair.geometry.dispose()
        }
        n.chair = up ? new Mesh(chairGeometry(up), new MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: n.alpha })) : null
        if (n.chair) this.group.add(n.chair)
        n.chairUp = up
      }
      if (n.chair) {
        n.chair.position.copy(v3(base))
        n.chair.visible = n.alpha > 0
      }
      n.post.geometry.setPositions([...v3(up ? [p[0], p[1], p[2] - HEAD_M / 2] : base).toArray(), ...top.toArray()])
      // Each label hangs off the cube's face on its side, so the cube never sits on its own label.
      const [dx, dz] = { above: [0, HEAD_M / 2], 'above-left': [0, HEAD_M / 2], 'above-right': [0, HEAD_M / 2], right: [HEAD_M / 2, 0], left: [-HEAD_M / 2, 0], 'below-right': [0, -HEAD_M / 2], 'below-left': [0, -HEAD_M / 2] }[nodeLabelSide(n.id)]
      this.view.moveLabel(n.label, v3([p[0] + dx, p[1], p[2] + dz]))
    }
    this.view.requestRender()
  }

  /** Shows each device as the board hears it: in full while heard, faint with "not heard" once it goes quiet,
   *  and not at all before it has ever been heard. */
  setHearing(hearing: ReadonlyMap<string, Hearing>) {
    this.hearing = hearing
    for (const n of this.nodes) {
      const h = hearing.get(n.id) ?? 'never'
      // Tamper (contract #533): a device that went silent while armed is drawn in full, in the fault colour,
      // with its "not heard" label, however long it has been quiet.
      const tampered = this.tamper.has(n.id)
      const quiet = tampered || h === 'lost'
      n.alphaTo = tampered || h === 'heard' ? 1 : h === 'lost' ? LOST_ALPHA : 0
      const name = NODES[n.id]?.name ?? n.id
      const text = quiet ? `${name}\nnot heard` : name // a second line: as wide as the name alone
      if (n.label.textContent !== text) n.label.textContent = text
      n.label.classList.toggle('room-label--node-lost', quiet && !tampered)
      n.label.classList.toggle('room-label--node-tamper', tampered)
      n.head.material.color.setHex(tampered ? FAULT : TEXT)
    }
    this.view.host.dataset.tamper = [...this.tamper].join(',')
    this.view.host.dataset.devices = this.nodes.filter((n) => n.alphaTo === 1).map((n) => n.id).join(',')
    this.view.host.dataset.devicesLost = this.nodes.filter((n) => n.alphaTo === LOST_ALPHA).map((n) => n.id).join(',')
    this.view.requestRender()
  }

  /** The devices state.tamper lists (silent while armed), or a replayed second's. */
  setTamper(nodes: readonly string[]) {
    const next = new Set(nodes)
    if (next.size === this.tamper.size && [...next].every((id) => this.tamper.has(id))) return
    this.tamper = next
    this.setHearing(this.hearing)
  }

  /** Fades each device toward how it is heard (140 ms in, 100 ms out). Returns true while any is still fading. */
  private fadeNodes(dt: number): boolean {
    let busy = false
    for (const n of this.nodes) {
      n.alpha = fade(n.alpha, n.alphaTo, dt)
      busy ||= n.alpha !== n.alphaTo
      n.head.material.opacity = n.alpha
      n.post.material.opacity = n.alpha * STAND_ALPHA
      n.head.visible = n.post.visible = n.alpha > 0
      if (n.chair) {
        n.chair.material.opacity = n.alpha
        n.chair.visible = n.alpha > 0
      }
      // The name stays readable on a quiet device: "not heard" is the point of showing it at all.
      n.label.style.opacity = String(n.alphaTo === LOST_ALPHA ? Math.min(1, n.alpha / LOST_ALPHA) : n.alpha)
      n.label.hidden = n.alpha === 0 && n.alphaTo === 0
    }
    return busy
  }

  /** Amber zone names for the zones the radio is weighing (pred.zone_set); red for a fired alert's zone. */
  markZones(zones: readonly number[], alertZone: number | null = null) {
    for (const [id, el] of this.zoneLabels) {
      el.classList.toggle('room-label--zone-set', zones.includes(id))
      el.classList.toggle('room-label--zone-alert', id === alertZone)
    }
  }
}
