import { Color, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import type { LinkState, StateMsg } from './contract'
import { LINK_IDS, nodePosition, parseLinkId, type Vec3 } from './frame'
import type { Mirror } from './mirror'
import { INK, INK_2, OLIVE } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// One thin ink line per radio link (contract section 3), drawn between the node heads.
// It dims as drop_db rises, turns olive when the link is in pred.why, and breaks into dashes when blind.

export interface BeamLook {
  status: string // ok | stale | blind | missing
  broken: boolean
  why: boolean
  opacity: number
  width: number
}

const FULL_DROP_DB = 12 // at this drop a link is as dim as it gets

export function beamLook(link: LinkState | undefined, why: boolean, blind: ReadonlySet<string>): BeamLook {
  const status = !link ? 'missing' : blind.has(link.id) ? 'blind' : link.status
  const broken = status === 'blind' || status === 'missing'
  const drop = Math.max(0, link?.drop_db ?? 0)
  const lit = 1 - 0.72 * Math.min(1, drop / FULL_DROP_DB)
  return {
    status,
    broken,
    why: why && !broken,
    // A link that explains the prediction stays readable however far it has dropped.
    opacity: broken ? 0.6 : status === 'stale' ? lit * 0.6 : why ? Math.max(lit, 0.8) : lit,
    width: why && !broken ? 3 : 1.5,
  }
}

const INK_C = new Color(INK)
const BROKEN_C = new Color(INK_2)
const OLIVE_C = new Color(OLIVE)

interface Beam {
  id: string
  line: Line2
  mat: LineMaterial
  label: HTMLElement
  look: BeamLook
  olive: number // 0..1, eased
}

export class Beams {
  private readonly beams: Beam[] = []
  private router: string | null = null

  constructor(private readonly view: RoomView, private readonly mirror: Mirror) {
    for (const id of LINK_IDS) {
      const mat = new LineMaterial({ color: INK, linewidth: 1.5, transparent: true, dashSize: 0.08, gapSize: 0.09 })
      const line = new Line2(new LineGeometry(), mat)
      const label = view.addLabel('no signal', new Vector3(), 'room-label--beam')
      label.hidden = true
      view.scene.add(line)
      this.beams.push({ id, line, mat, label, look: beamLook(undefined, false, new Set()), olive: 0 })
    }
    view.onResize((w, h) => {
      for (const b of this.beams) b.mat.resolution.set(w, h)
    })
    view.addAnimator((dt) => this.ease(dt))
    this.place('S-home')
  }

  update(state: StateMsg) {
    if (state.router !== this.router) this.place(state.router)
    const blind = new Set(state.health?.blind ?? [])
    const why = new Set(state.pred?.why ?? [])
    for (const b of this.beams) {
      const link = state.links.find((l) => l.id === b.id)
      b.look = beamLook(link, why.has(b.id), blind)
      if (b.mat.dashed !== b.look.broken) b.mat.dashed = b.look.broken
      b.label.hidden = !b.look.broken
      const drop = link?.drop_db
      this.mirror.set(
        `beam-${b.id}`,
        { 'drop-db': drop == null ? null : drop.toFixed(1), status: b.look.status, why: String(b.look.why) },
        `${b.id}: ${b.look.status}${drop == null ? '' : `, drop ${drop.toFixed(1)} dB`}${b.look.why ? ', explains the prediction' : ''}`,
      )
    }
    this.view.requestRender()
  }

  /** Puts every line between its nodes. Two links between the same nodes sit side by side. */
  private place(router: string) {
    this.router = router
    for (const b of this.beams) {
      const parts = parseLinkId(b.id)!
      const a = nodePosition(parts.tx, router)
      const z = nodePosition(parts.rx, router)
      const twin = LINK_IDS.filter((id) => id !== b.id && id.startsWith(`${parts.tx}>${parts.rx}:`)).length > 0
      const shift = twin ? (parts.kind === 'wifi' ? 0.035 : -0.035) : 0
      const [ax, ay, az] = offset(a, z, shift)
      const [zx, zy, zz] = offset(z, a, -shift)
      const p = v3([ax, ay, az])
      const q = v3([zx, zy, zz])
      ;(b.line.geometry as LineGeometry).setPositions([p.x, p.y, p.z, q.x, q.y, q.z])
      b.line.computeLineDistances()
      this.view.moveLabel(b.label, p.clone().lerp(q, 0.5).setY(p.y + 0.06))
    }
    this.view.requestRender()
  }

  /** Eases width, opacity and colour toward each link's look. Returns true while still moving. */
  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 160)
    let busy = false
    for (const b of this.beams) {
      const { mat, look } = b
      mat.opacity += (look.opacity - mat.opacity) * k
      mat.linewidth += (look.width - mat.linewidth) * k
      b.olive += ((look.why ? 1 : 0) - b.olive) * k
      mat.color.copy(look.broken ? BROKEN_C : INK_C).lerp(OLIVE_C, b.olive)
      busy ||= Math.abs(look.opacity - mat.opacity) > 0.005 || Math.abs(look.width - mat.linewidth) > 0.02 ||
        Math.abs((look.why ? 1 : 0) - b.olive) > 0.005
    }
    return busy
  }
}

/** Moves a link end sideways (in the floor plane) by `by` metres, perpendicular to the link. */
function offset(from: Vec3, to: Vec3, by: number): Vec3 {
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  const len = Math.hypot(dx, dy) || 1
  return [from[0] - (dy / len) * by, from[1] + (dx / len) * by, from[2]]
}
