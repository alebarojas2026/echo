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
import { HOME_SPOT, NODES, SQUARE_M, ZONES, nodePosition, toScene, type NodeId, type Vec3 } from './frame'
import { Glide3 } from './motion'
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

/** The plinth, low walls and slab shadow (replaced by a room scan when there is one), and the square. */
function buildShell(): { room: Group; square: Group } {
  const g = new Group()
  const sq = new Group()
  const west = -MARGIN_M
  const east = SQUARE_M + MARGIN_M
  const north = SQUARE_M + MARGIN_M
  const south = -SOUTH_M
  const sizeX = east - west
  const sizeY = north - south
  const mid = SQUARE_M / 2
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

  // The sensing square and its zone lines as thin strips, so they hold up at 0.85 render scale and 3 m.
  const s = SQUARE_M
  const lines: Part[] = []
  const strip = (a: Vec3, b: Vec3, wide: number, color: number) => {
    const [ax, , az] = toScene(a)
    const [bx, , bz] = toScene(b)
    const len = Math.hypot(bx - ax, bz - az)
    const ang = Math.atan2(-(bz - az), bx - ax)
    lines.push({ geom: new PlaneGeometry(len + wide, wide), light: color, dark: color, at: at((ax + bx) / 2, 0.001, (az + bz) / 2, -Math.PI / 2, ang) })
  }
  const edges: [Vec3, Vec3][] = [
    [[0, 0, 0], [s, 0, 0]],
    [[s, 0, 0], [s, s, 0]],
    [[s, s, 0], [0, s, 0]],
    [[0, s, 0], [0, 0, 0]],
  ]
  for (const [a, b] of edges) strip(a, b, 0.014, SQUARE)
  strip([mid, 0, 0], [mid, s, 0], 0.007, EDGE)
  strip([0, mid, 0], [s, mid, 0], 0.007, EDGE)
  sq.add(new Mesh(shadedGeometry(lines), new MeshBasicMaterial({ vertexColors: true })))
  return { room: g, square: sq }
}

/** Segment pairs that join the points in order and close the loop. */
function outline(pts: Vec3[]): Vec3[] {
  return pts.flatMap((p, i) => [p, pts[(i + 1) % pts.length]])
}

const HEAD_M = 0.08
const ZONE_IN_X = 0.1 // zone names start (west zones) or end (east zones) this far in from the side

/** What each node is called on screen and which side of its cube the name goes. */
const NODE_LABELS: Record<NodeId, { text: string; side: 'above' | 'right' | 'left' }> = {
  unoq: { text: 'UNO Q', side: 'above' },
  pi5: { text: 'Pi 5 router', side: 'right' },
  east: { text: 'East beacon', side: 'right' },
  west: { text: 'West beacon', side: 'left' },
}

interface NodeMesh {
  id: NodeId
  head: Mesh
  post: LineSegments
  label: HTMLElement
}

export class Stage {
  readonly group = new Group()
  /** The drawn floor and walls; hidden while a room scan stands in for them. */
  readonly drawnRoom: Group
  private readonly nodes: NodeMesh[] = []
  private readonly zoneLabels = new Map<number, HTMLElement>()
  private readonly routerGlide = new Glide3(nodePosition('pi5', HOME_SPOT))

  constructor(private readonly view: RoomView) {
    const { room, square } = buildShell()
    this.drawnRoom = room
    this.group.add(room, square)

    // Zone names sit in each zone's outer corner, clear of the links that cross the middle. West zones read
    // from their west edge, east zones end at their east edge.
    const inX = ZONE_IN_X
    const inY = 0.2
    for (const z of ZONES) {
      const east = z.id === 2 || z.id === 4
      const north = z.id === 1 || z.id === 2
      const at = v3([east ? SQUARE_M - inX : inX, north ? SQUARE_M - inY : inY, 0])
      this.zoneLabels.set(z.id, view.addLabel(`${z.id} ${z.name}`, at, `room-label--zone${east ? ' room-label--zone-east' : ''}`))
    }

    const headGeom = new BoxGeometry(HEAD_M, HEAD_M, HEAD_M)
    const ink = new MeshBasicMaterial({ color: TEXT })
    const postMat = new LineBasicMaterial({ color: EDGE })
    const postGeom = new BufferGeometry()
    postGeom.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 0, 1, 0], 3))
    for (const info of Object.values(NODES)) {
      const head = new Mesh(headGeom, ink)
      const post = new LineSegments(postGeom, postMat)
      this.group.add(head, post)
      const label = view.addLabel(NODE_LABELS[info.id].text, new Vector3(), `room-label--node room-label--${NODE_LABELS[info.id].side}`)
      this.nodes.push({ id: info.id, head, post, label })
    }
    this.putNodes()
    view.addAnimator((dt) => {
      const moving = this.routerGlide.step(dt)
      if (moving) this.putNodes()
      return moving
    })
    view.scene.add(this.group)
  }

  /** Puts every node at its spot; the router glides (600 ms) to the spot in state.router. */
  placeNodes(router: string | null | undefined) {
    this.routerGlide.set(nodePosition('pi5', router))
    this.view.requestRender()
  }

  private putNodes() {
    for (const n of this.nodes) {
      const p = n.id === 'pi5' ? this.routerGlide.now() : nodePosition(n.id, null)
      const top = v3(p)
      n.head.position.copy(top)
      n.post.position.copy(v3([p[0], p[1], 0]))
      n.post.scale.y = p[2]
      // Each label hangs off the cube's face on its side, so the cube never sits on its own label.
      const [dx, dz] = { above: [0, HEAD_M / 2], right: [HEAD_M / 2, 0], left: [-HEAD_M / 2, 0] }[NODE_LABELS[n.id].side]
      this.view.moveLabel(n.label, v3([p[0] + dx, p[1], p[2] + dz]))
    }
    this.view.requestRender()
  }

  /** Amber zone names for the zones the radio is weighing (pred.zone_set); red for a fired alert's zone. */
  markZones(zones: readonly number[], alertZone: number | null = null) {
    for (const [id, el] of this.zoneLabels) {
      el.classList.toggle('room-label--zone-set', zones.includes(id))
      el.classList.toggle('room-label--zone-alert', id === alertZone)
    }
  }
}
