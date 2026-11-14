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
import { NODES, SQUARE_M, ZONES, nodePosition, toScene, type NodeId, type Vec3 } from './frame'
import { EDGE, FLOOR, SQUARE, TEXT } from './palette'
import type { RoomView } from './view'

// The still parts of the room: floor, the 2 x 2 m square and its zones, two back walls, and the four nodes.

const MARGIN_M = 0.5
const WALL_M = 0.35 // low walls edge the floor without framing the scene in long diagonals

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

/** The drawn floor and back walls (replaced by a room scan when there is one), and the square with its zones. */
function buildShell(): { room: Group; square: Group } {
  const g = new Group()
  const sq = new Group()
  const lo = -MARGIN_M
  const hi = SQUARE_M + MARGIN_M
  const size = hi - lo
  const mid = SQUARE_M / 2
  const card = new MeshBasicMaterial({ color: FLOOR })

  const floor = new Mesh(new PlaneGeometry(size, size), card)
  floor.rotation.x = -Math.PI / 2
  floor.position.set(0, -0.002, 0)
  g.add(floor)

  const north = new Mesh(new PlaneGeometry(size, WALL_M), card)
  north.position.copy(v3([mid, hi, WALL_M / 2]))
  g.add(north)

  const west = new Mesh(new PlaneGeometry(size, WALL_M), card)
  west.rotation.y = Math.PI / 2
  west.position.copy(v3([lo, mid, WALL_M / 2]))
  g.add(west)

  // Floor edge, wall tops and the three wall corners.
  const w = WALL_M
  const walls: Vec3[] = [[lo, hi, w], [hi, hi, w], [lo, lo, w], [lo, hi, w], [lo, hi, 0], [lo, hi, w],
    [hi, hi, 0], [hi, hi, w], [lo, lo, 0], [lo, lo, w]]
  const floorEdge = outline([[lo, lo, 0], [hi, lo, 0], [hi, hi, 0], [lo, hi, 0]])
  g.add(segments([...floorEdge, ...walls], new LineBasicMaterial({ color: EDGE })))

  // The sensing square and its four zones.
  const s = SQUARE_M
  sq.add(segments(outline([[0, 0, 0], [s, 0, 0], [s, s, 0], [0, s, 0]]), new LineBasicMaterial({ color: SQUARE })))
  const dash = new LineDashedMaterial({ color: EDGE, dashSize: 0.06, gapSize: 0.05 })
  sq.add(segments([[mid, 0, 0], [mid, s, 0], [0, mid, 0], [s, mid, 0]], dash))
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
      const label = view.addLabel('', at, `room-label--zone${east ? ' room-label--zone-east' : ''}`)
      // The second line only shows while the no-movement alert is on in this zone: red always comes with a word.
      label.innerHTML = '<span></span><span class="room-label__alert">No movement</span>'
      label.firstElementChild!.textContent = `${z.id} ${z.name}`
      this.zoneLabels.set(z.id, label)
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
    this.placeNodes('S-home')
    view.scene.add(this.group)
  }

  /** Puts every node at its spot; the router follows state.router. */
  placeNodes(router: string | null | undefined) {
    for (const n of this.nodes) {
      const p = nodePosition(n.id, router)
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
