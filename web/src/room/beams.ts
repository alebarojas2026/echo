import { Color, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import type { LinkState, StateMsg } from './contract'
import { HOME_SPOT, LINK_IDS, floorSize, nodePosition, parseLinkId, routerId, type NodeId, type Vec3 } from './frame'
import type { Mirror } from './mirror'
import { follow, Glide3, Held, TAU } from './motion'
import { ACTION, FAULT, LINK, PERSON } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// One thin neutral line per radio link (contract section 3), drawn between the node heads.
// It dims as drop_db rises, turns amber (the person's colour) when the link is in pred.why and is itself dropping
// (explains, below), and breaks into dashes when blind.
// A link whose straight path never passes over the floor a person stands on (on the desk layout, one between two
// devices on the desk) is drawn faint while nothing is happening on it: the links a person can cut read first.

export interface BeamLook {
  status: string // ok | stale | blind | missing
  broken: boolean
  why: boolean
  opacity: number
  width: number
}

const FULL_DROP_DB = 12 // at this drop a link is as dim as it gets
/** How strong a link that never passes over the floor is drawn, next to one that does, while it explains nothing. */
const OFF_FLOOR = 0.3

/** Whether the straight line from a to b passes over the floor a person can be in (floorSize, from nodes.json),
 *  not just along its edge. On the square every link does; on the desk, a link between two desk devices doesn't. */
export function overFloor(a: Vec3, b: Vec3): boolean {
  const [fw, fh] = floorSize()
  const inset = 0.01
  for (let i = 0; i <= 64; i++) {
    const x = a[0] + ((b[0] - a[0]) * i) / 64
    const y = a[1] + ((b[1] - a[1]) * i) / 64
    if (x > inset && x < fw - inset && y > inset && y < fh - inset) return true
  }
  return false
}

/** A link is dropping at this much under its baseline: the contract's own number (section 6, the router advice). */
export const DROPPING_DB = 3

/**
 * The drop at which a listed link lights, as a setting: ?amber_db=<dB> on the page's address, else 3 dB. On the
 * real kit the weakest step-on drops a line by about 3 dB and an empty spot stays within 2, so the number sits
 * close to both; it is a setting so it can follow whatever level the brain settles on for "present" without a
 * new build. Kept between 1 and 20 dB.
 */
export function amberDb(params: URLSearchParams): number {
  const v = Number(params.get('amber_db'))
  return params.get('amber_db') !== null && v >= 1 && v <= 20 ? v : DROPPING_DB
}

/**
 * Whether a link is one the person's body is cutting right now: listed in pred.why, and its own drop_db at `bar`
 * (3 dB unless set) or more. pred.why names the brain's top links whether or not they moved, so on its own it would light a line that
 * sits at its baseline. A null drop (before the baseline) is not a drop.
 */
export function explains(link: LinkState | undefined, inWhy: boolean, bar = DROPPING_DB): boolean {
  return inWhy && (link?.drop_db ?? 0) >= bar
}

export function beamLook(link: LinkState | undefined, why: boolean, blind: ReadonlySet<string>, onFloor = true): BeamLook {
  const status = !link ? 'missing' : blind.has(link.id) ? 'blind' : link.status
  const broken = status === 'blind' || status === 'missing'
  const drop = Math.max(0, link?.drop_db ?? 0)
  const lit = 1 - 0.72 * Math.min(1, drop / FULL_DROP_DB)
  return {
    status,
    broken,
    why: why && !broken,
    // A link that explains the prediction stays readable however far it has dropped.
    opacity: broken ? 0.6 : why ? Math.max(lit, 0.8) : (status === 'stale' ? lit * 0.6 : lit) * (onFloor ? 1 : OFF_FLOOR),
    width: why && !broken ? 5 : 3, // 1.5 px is half an arcminute from 3 m; 3 px is the least that reads
  }
}

export const WHY_ON_MS = 300
export const WHY_OFF_MS = 500

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
  /** Explains the prediction, as shown: lights after 300 ms of it, lets go after 500 ms without. A real Bluetooth
   *  link wobbles a few dB with nobody there, so one at the 3 dB line would otherwise flicker. */
  why: Held<boolean>
  /** Its straight path passes over the floor a person stands on (overFloor). */
  onFloor: boolean
}

/** The two nodes a link joins, in a fixed order, so twin links (wifi and ble) share one key. */
export function nodePair(id: string): string {
  const p = parseLinkId(id)
  return p ? [p.tx, p.rx].sort().join('-') : id
}

/**
 * How far each link sits from the straight line between its two nodes, so links between the same two nodes
 * (Wi-Fi and Bluetooth, or both directions) lie side by side 7 cm apart instead of on top of each other.
 * The shift is to the left of the link's own direction, so it holds whichever way the link runs.
 */
export function laneShifts(ids: readonly string[]): Map<string, number> {
  const groups = new Map<string, string[]>()
  for (const id of ids) groups.set(nodePair(id), [...(groups.get(nodePair(id)) ?? []), id])
  const out = new Map<string, number>()
  for (const group of groups.values()) {
    group.forEach((id, i) => {
      const lane = ((group.length - 1) / 2 - i) * 0.07
      const p = parseLinkId(id)
      // Lanes are counted along the pair's sorted direction; a link running the other way flips its side.
      const forward = !p || [p.tx, p.rx].sort()[0] === p.tx
      out.set(id, forward ? lane : -lane)
    })
  }
  return out
}

export class Beams {
  private readonly beams: Beam[] = []
  /** One "no signal" label per node pair, however many links run between the two nodes. */
  private readonly pairLabels = new Map<string, HTMLElement>()
  /** Shown instead of any per-link label while state.links is still empty (no readings yet). */
  private readonly waiting: HTMLElement
  private router: string | null = null
  /** The router's head glides to a new spot (600 ms); the links that end on it follow. */
  private readonly pi5 = new Glide3(nodePosition(routerId(), HOME_SPOT))
  /** The link that just carried a wave check-in, drawn green and wide while the wave shows. */
  private waveLink: string | null = null

  constructor(private readonly view: RoomView, private readonly mirror: Mirror, private readonly amberAt = DROPPING_DB) {
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
        why: new Held<boolean>(false, (on) => (on ? WHY_ON_MS : WHY_OFF_MS)), onFloor: true })
    }
    const [fw, fh] = floorSize()
    this.waiting = view.addLabel('Waiting for radio readings', v3([fw / 2, fh / 2, 0]), 'room-label--caption')
    this.waiting.hidden = true
    view.onResize((w, h) => {
      for (const b of this.beams) b.mat.resolution.set(w, h)
    })
    view.addAnimator((dt) => this.ease(dt))
    this.router = HOME_SPOT
    this.placeAt(nodePosition(routerId(), HOME_SPOT))
  }

  setWave(link: string | null) {
    if (link === this.waveLink) return
    this.waveLink = link
    this.view.requestRender()
  }

  update(state: StateMsg, nowMs = performance.now()) {
    if (state.router !== this.router) {
      this.router = state.router
      this.pi5.set(nodePosition(routerId(), state.router))
      this.view.requestRender()
    }
    const blind = new Set(state.health?.blind ?? [])
    const why = new Set(state.pred?.why ?? [])
    const waiting = state.links.length === 0
    const brokenPairs = new Set<string>()
    for (const b of this.beams) {
      const link = state.links.find((l) => l.id === b.id)
      b.look = beamLook(link, b.why.update(explains(link, why.has(b.id), this.amberAt), nowMs), blind, b.onFloor)
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

  /** Puts every line between its nodes, with the router's head at `pi5`. Links between the same two nodes
   *  sit side by side. */
  private placeAt(pi5: Vec3) {
    const router = routerId()
    const at = (id: NodeId) => (id === router ? pi5 : nodePosition(id, this.router))
    const shifts = laneShifts(this.beams.map((b) => b.id))
    const labelled = new Set<string>()
    for (const b of this.beams) {
      const parts = parseLinkId(b.id)!
      const a = at(parts.tx)
      const z = at(parts.rx)
      b.onFloor = overFloor(a, z)
      const shift = shifts.get(b.id) ?? 0
      const [ax, ay, az] = offset(a, z, shift)
      const [zx, zy, zz] = offset(z, a, -shift)
      const p = v3([ax, ay, az])
      const q = v3([zx, zy, zz])
      ;(b.line.geometry as LineGeometry).setPositions([p.x, p.y, p.z, q.x, q.y, q.z])
      b.line.computeLineDistances()
      // A pair's label sits on the middle of the unshifted line between its nodes, one spot for all its links.
      if (!labelled.has(b.pair)) {
        labelled.add(b.pair)
        this.view.moveLabel(this.pairLabels.get(b.pair)!, v3(a).lerp(v3(z), 0.5))
      }
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
