import { Color, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import type { LinkState, StateMsg } from './contract'
import { LINK_IDS, SQUARE_M, nodePosition, parseLinkId, type NodeId, type Vec3 } from './frame'
import type { Mirror } from './mirror'
import { follow, Glide3, Held, TAU } from './motion'
import { ACTION, FAULT, LINK, PERSON } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// One thin neutral line per radio link (contract section 3), drawn between the node heads.
// It dims as drop_db rises, turns amber (the person's colour) when the link is in pred.why, and breaks into dashes when blind.

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
    width: why && !broken ? 5 : 3, // 1.5 px is half an arcminute from 3 m; 3 px is the least that reads
  }
}

const LINK_C = new Color(LINK)
const BROKEN_C = new Color(FAULT)
const WHY_C = new Color(PERSON)
const WAVE_C = new Color(ACTION)

interface Beam {
  id: string
  pair: string
  line: Line2
  mat: LineMaterial
  look: BeamLook
  amber: number // 0..1, eased toward the person colour
  green: number // 0..1, eased toward the check-in colour
  /** In pred.why, as shown: lights after 300 ms in the list, lets go after 800 ms out of it. */
  why: Held<boolean>
}

/** The two nodes a link joins, in a fixed order, so twin links (wifi and ble) share one key. */
export function nodePair(id: string): string {
  const p = parseLinkId(id)
  return p ? [p.tx, p.rx].sort().join('-') : id
}

export class Beams {
  private readonly beams: Beam[] = []
  /** One "no signal" label per node pair, however many links run between the two nodes. */
  private readonly pairLabels = new Map<string, HTMLElement>()
  /** Shown instead of any per-link label while state.links is still empty (no readings yet). */
  private readonly waiting: HTMLElement
  private router: string | null = null
  /** The router's head glides to a new spot (600 ms); the links that end on it follow. */
  private readonly pi5 = new Glide3(nodePosition('pi5', 'S-home'))
  /** The link that just carried a wave check-in, drawn green and wide while the wave shows. */
  private waveLink: string | null = null

  constructor(private readonly view: RoomView, private readonly mirror: Mirror) {
    for (const id of LINK_IDS) {
      const mat = new LineMaterial({ color: LINK, linewidth: 3, transparent: true, dashSize: 0.08, gapSize: 0.09 })
      const line = new Line2(new LineGeometry(), mat)
      view.scene.add(line)
      const pair = nodePair(id)
      if (!this.pairLabels.has(pair)) {
        const label = view.addLabel('no signal', new Vector3(), 'room-label--beam')
        label.hidden = true
        this.pairLabels.set(pair, label)
      }
      this.beams.push({ id, pair, line, mat, look: beamLook(undefined, false, new Set()), amber: 0, green: 0,
        why: new Held<boolean>(false, (on) => (on ? 300 : 800)) })
    }
    this.waiting = view.addLabel('Waiting for radio readings', v3([SQUARE_M / 2, SQUARE_M / 2, 0]), 'room-label--caption')
    this.waiting.hidden = true
    view.onResize((w, h) => {
      for (const b of this.beams) b.mat.resolution.set(w, h)
    })
    view.addAnimator((dt) => this.ease(dt))
    this.router = 'S-home'
    this.placeAt(nodePosition('pi5', 'S-home'))
  }

  setWave(link: string | null) {
    if (link === this.waveLink) return
    this.waveLink = link
    this.view.requestRender()
  }

  update(state: StateMsg, nowMs = performance.now()) {
    if (state.router !== this.router) {
      this.router = state.router
      this.pi5.set(nodePosition('pi5', state.router))
      this.view.requestRender()
    }
    const blind = new Set(state.health?.blind ?? [])
    const why = new Set(state.pred?.why ?? [])
    const waiting = state.links.length === 0
    const brokenPairs = new Set<string>()
    for (const b of this.beams) {
      const link = state.links.find((l) => l.id === b.id)
      b.look = beamLook(link, b.why.update(why.has(b.id), nowMs), blind)
      if (b.mat.dashed !== b.look.broken) b.mat.dashed = b.look.broken
      if (b.look.broken) brokenPairs.add(b.pair)
      const drop = link?.drop_db
      this.mirror.set(
        `beam-${b.id}`,
        { 'drop-db': drop == null ? null : drop.toFixed(1), status: b.look.status, why: String(b.look.why) },
        `${b.id}: ${b.look.status}${drop == null ? '' : `, drop ${drop.toFixed(1)} dB`}${b.look.why ? ', explains the prediction' : ''}`,
      )
    }
    for (const [pair, label] of this.pairLabels) label.hidden = waiting || !brokenPairs.has(pair)
    this.waiting.hidden = !waiting
    this.view.requestRender()
  }

  /** Puts every line between its nodes, with the router's head at `pi5`. Two links between the same nodes
   *  sit side by side. */
  private placeAt(pi5: Vec3) {
    const at = (id: NodeId) => (id === 'pi5' ? pi5 : nodePosition(id, this.router))
    for (const b of this.beams) {
      const parts = parseLinkId(b.id)!
      const a = at(parts.tx)
      const z = at(parts.rx)
      const twin = LINK_IDS.filter((id) => id !== b.id && id.startsWith(`${parts.tx}>${parts.rx}:`)).length > 0
      const shift = twin ? (parts.kind === 'wifi' ? 0.035 : -0.035) : 0
      const [ax, ay, az] = offset(a, z, shift)
      const [zx, zy, zz] = offset(z, a, -shift)
      const p = v3([ax, ay, az])
      const q = v3([zx, zy, zz])
      ;(b.line.geometry as LineGeometry).setPositions([p.x, p.y, p.z, q.x, q.y, q.z])
      b.line.computeLineDistances()
      // A pair's label sits on the middle of its unshifted link, so twins share one spot.
      if (!twin || parts.kind === 'wifi') this.view.moveLabel(this.pairLabels.get(b.pair)!, v3(a).lerp(v3(z), 0.5))
    }
    this.view.requestRender()
  }

  /** Eases width, opacity and colour toward each link's look. Returns true while still moving. */
  private ease(dt: number): boolean {
    // Dimming follows the noisy drop slowly; the colour and width change at the pace of new words.
    const kData = follow(dt, TAU.data)
    const k = follow(dt, TAU.in)
    let busy = false
    if (this.pi5.step(dt)) {
      this.placeAt(this.pi5.now())
      busy = true
    }
    for (const b of this.beams) {
      const { mat, look } = b
      mat.opacity += (look.opacity - mat.opacity) * kData
      const wave = b.id === this.waveLink && !look.broken
      const width = wave ? 7 : look.width
      mat.linewidth += (width - mat.linewidth) * k
      b.amber += ((look.why ? 1 : 0) - b.amber) * k
      b.green += ((wave ? 1 : 0) - b.green) * k
      mat.color.copy(look.broken ? BROKEN_C : LINK_C).lerp(WHY_C, b.amber).lerp(WAVE_C, b.green)
      if (wave) mat.opacity += (1 - mat.opacity) * k
      busy ||= Math.abs((wave ? 1 : look.opacity) - mat.opacity) > 0.005 || Math.abs(width - mat.linewidth) > 0.02 ||
        Math.abs((wave ? 1 : 0) - b.green) > 0.005 ||
        Math.abs((look.why ? 1 : 0) - b.amber) > 0.005
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
