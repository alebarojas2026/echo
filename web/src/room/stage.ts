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
import { HOME_SPOT, NODES, SIZE_M, STRIP_M, ZONES, ZONE_SPLIT_X_M, floorSize, nodeLabelSide, nodePosition, routerId, toScene, zoneRect, zoneSide, type NodeId, type Vec3 } from './frame'
import type { Hearing } from './heard'
import { fade, Glide3 } from './motion'
import { EDGE, FLOOR, SQUARE, TEXT, WALL_SHADE } from './palette'
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
  if (STRIP_M && ZONE_SPLIT_X_M !== null) {
    strip([ZONE_SPLIT_X_M, 0, 0], [ZONE_SPLIT_X_M, fh, 0], 0.007, EDGE) // one line between the strip's two zones
  } else {
    strip([fw / 2, 0, 0], [fw / 2, fh, 0], 0.007, EDGE)
    strip([0, fh / 2, 0], [fw, fh / 2, 0], 0.007, EDGE)
  }
  sq.add(new Mesh(shadedGeometry(lines), new MeshBasicMaterial({ vertexColors: true })))

  // The desk behind the strip: a plain top from the strip's back edge to the layout's, at desk height.
  if (STRIP_M) {
    const depth = SIZE_M[1] - STRIP_M[1]
    const [dx, , dz] = toScene([SIZE_M[0] / 2, STRIP_M[1] + depth / 2, 0])
    const top: Part = { geom: new BoxGeometry(SIZE_M[0], 0.03, depth), light: mix(FLOOR, EDGE, 0.5), dark: mix(FLOOR, WALL_SHADE, 0.6), at: at(dx, DESK_TOP_M - 0.015, dz) }
    sq.add(new Mesh(shadedGeometry([top]), new MeshBasicMaterial({ vertexColors: true })))
  }
  return { room: g, square: sq }
}

/** Segment pairs that join the points in order and close the loop. */
function outline(pts: Vec3[]): Vec3[] {
  return pts.flatMap((p, i) => [p, pts[(i + 1) % pts.length]])
}

const HEAD_M = 0.08
const ZONE_IN_X = 0.1 // zone names start (west zones) or end (east zones) this far in from the side

/**
 * Where a node's stand meets something: the floor on the square; on the desk layout the desk top for a node on
 * the desk, or the desk's edge for a beacon on an arm over the aisle (the arm runs level to its tip).
 */
export function standBase([x, y, z]: Vec3): Vec3 {
  if (!STRIP_M) return [x, y, 0]
  return y >= STRIP_M[1] - 0.01 ? [x, y, DESK_TOP_M] : [x, STRIP_M[1], z]
}

interface NodeMesh {
  id: NodeId
  head: Mesh<BoxGeometry, MeshBasicMaterial>
  post: LineSegments<BufferGeometry, LineBasicMaterial>
  label: HTMLElement
  /** 0..1 as drawn, and where it is heading: 1 heard, LOST_ALPHA heard before but quiet now, 0 never heard. */
  alpha: number
  alphaTo: number
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
      const at = v3([east ? x1 - inX : x0 + inX, north ? y1 - inY : y0 + inY, 0])
      this.zoneLabels.set(z.id, view.addLabel(`${z.id} ${z.name}`, at, `room-label--zone${east ? ' room-label--zone-east' : ''}`))
    }

    // Devices are live (heard.ts): each starts unseen and fades in once the board hears it.
    const headGeom = new BoxGeometry(HEAD_M, HEAD_M, HEAD_M)
    for (const info of Object.values(NODES)) {
      const head = new Mesh(headGeom, new MeshBasicMaterial({ color: TEXT, transparent: true, opacity: 0 }))
      const postGeom = new BufferGeometry()
      postGeom.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 0, 1, 0], 3))
      const post = new LineSegments(postGeom, new LineBasicMaterial({ color: EDGE, transparent: true, opacity: 0 }))
      head.visible = post.visible = false
      this.group.add(head, post)
      const label = view.addLabel(info.name, new Vector3(), `room-label--node room-label--${nodeLabelSide(info.id)}`)
      label.hidden = true
      this.nodes.push({ id: info.id, head, post, label, alpha: 0, alphaTo: 0 })
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

  private putNodes() {
    const router = routerId()
    for (const n of this.nodes) {
      const p = n.id === router ? this.routerGlide.now() : nodePosition(n.id, null)
      const top = v3(p)
      n.head.position.copy(top)
      // The stand: a line from the floor, the desk top, or the desk's edge (an arm) up to the head.
      const base = v3(standBase(p))
      const stand = n.post.geometry.getAttribute('position') as Float32BufferAttribute
      stand.set([base.x, base.y, base.z, top.x, top.y, top.z])
      stand.needsUpdate = true
      n.post.geometry.computeBoundingSphere()
      // Each label hangs off the cube's face on its side, so the cube never sits on its own label.
      const [dx, dz] = { above: [0, HEAD_M / 2], right: [HEAD_M / 2, 0], left: [-HEAD_M / 2, 0] }[nodeLabelSide(n.id)]
      this.view.moveLabel(n.label, v3([p[0] + dx, p[1], p[2] + dz]))
    }
    this.view.requestRender()
  }

  /** Shows each device as the board hears it: in full while heard, faint with "not heard" once it goes quiet,
   *  and not at all before it has ever been heard. */
  setHearing(hearing: ReadonlyMap<string, Hearing>) {
    for (const n of this.nodes) {
      const h = hearing.get(n.id) ?? 'never'
      n.alphaTo = h === 'heard' ? 1 : h === 'lost' ? LOST_ALPHA : 0
      const name = NODES[n.id]?.name ?? n.id
      const text = h === 'lost' ? `${name}\nnot heard` : name // a second line: as wide as the name alone
      if (n.label.textContent !== text) n.label.textContent = text
      n.label.classList.toggle('room-label--node-lost', h === 'lost')
    }
    this.view.host.dataset.devices = this.nodes.filter((n) => n.alphaTo === 1).map((n) => n.id).join(',')
    this.view.host.dataset.devicesLost = this.nodes.filter((n) => n.alphaTo === LOST_ALPHA).map((n) => n.id).join(',')
    this.view.requestRender()
  }

  /** Fades each device toward how it is heard (140 ms in, 100 ms out). Returns true while any is still fading. */
  private fadeNodes(dt: number): boolean {
    let busy = false
    for (const n of this.nodes) {
      n.alpha = fade(n.alpha, n.alphaTo, dt)
      busy ||= n.alpha !== n.alphaTo
      n.head.material.opacity = n.post.material.opacity = n.alpha
      n.head.visible = n.post.visible = n.alpha > 0
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
