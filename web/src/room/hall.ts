import { Color, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import type { HallLink } from './contract'
import { HALL_BEACONS, nodePosition, type Vec3 } from './frame'
import { Mirror } from './mirror'
import { fade } from './motion'
import { LINK, PERSON } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// Hall links (state.hall): long paths from a far beacon to a receiver at the desk, drawn across the hall model.
// They say one thing only: "movement on this path", never who, where along it, or how many. Quiet paths are
// neutral and fainter than the square's links, so the square stays the hero; a moving path turns person blue with
// the words. A stale path, or one whose beacon has no spot yet, is not drawn: these links are optional, and a
// missing one is not a fault. Two links from the same beacon nearly overlap at hall scale, so each beacon gets
// one line, blue when any of its links is moving, and the words once.

/** How each beacon's path looks this frame, from its rows. */
export interface PathLook {
  tx: string
  show: boolean
  moving: boolean
  /** The beacon's floor spot: where it was placed (nodes.json, saved by align mode), else the brain's xy_m. The
   *  brain reads positions only when it starts, so after a save its xy_m is still the old spot. */
  xy: [number, number] | null
  /** The receiver the line runs to: the board when it hears the beacon, else the first that does. */
  rx: string | null
}

export function pathLooks(rows: readonly HallLink[] | undefined): PathLook[] {
  const byTx = new Map<string, HallLink[]>()
  for (const r of rows ?? []) byTx.set(r.tx, [...(byTx.get(r.tx) ?? []), r])
  return [...byTx].map(([tx, list]) => {
    const live = list.filter((r) => !r.stale)
    const placed = HALL_BEACONS.find((b) => b.node === tx)?.xyz
    const xy = placed ? ([placed[0], placed[1]] as [number, number]) : (live.find((r) => r.xy_m)?.xy_m ?? null)
    const rx = (live.find((r) => r.rx === 'unoq') ?? live[0])?.rx ?? null
    return { tx, show: live.length > 0 && !!xy && !!rx, moving: live.some((r) => r.moving), xy, rx }
  })
}

const LINK_Z_M = 1.0 // the square's links run between heads 1 m up
const WORDS_AT = 0.65 // the words sit this far from the receiver toward the beacon, clear of the square

interface Path {
  line: Line2
  mat: LineMaterial
  words: HTMLElement
  alpha: number
  alphaTo: number
  amber: number
  amberTo: number
  wordsAlpha: number
  wordsTo: number
}

export class HallPaths {
  private readonly paths = new Map<string, Path>()
  private readonly mirror: Mirror

  constructor(private readonly view: RoomView) {
    this.mirror = new Mirror(view.host, 'hall-beams', 'Hall links')
    view.addAnimator((dt) => this.ease(dt))
  }

  update(rows: readonly HallLink[] | undefined, router: string | null) {
    for (const r of rows ?? []) {
      this.mirror.set(
        `hall-${r.id}`,
        { moving: String(r.moving), stale: String(r.stale), activity: r.activity.toFixed(2) },
        `${r.id}: ${r.stale ? 'stale' : r.moving ? 'movement on this path' : 'quiet'}`,
      )
    }
    const looks = pathLooks(rows)
    for (const look of looks) {
      const p = this.path(look.tx)
      p.alphaTo = look.show ? 1 : 0
      p.amberTo = look.show && look.moving ? 1 : 0
      p.wordsTo = p.amberTo
      if (!look.show) continue
      const a: Vec3 = [look.xy![0], look.xy![1], LINK_Z_M]
      const b = nodePosition(look.rx!, router)
      const pa = v3(a)
      const pb = v3(b)
      ;(p.line.geometry as LineGeometry).setPositions([pa.x, pa.y, pa.z, pb.x, pb.y, pb.z])
      this.view.moveLabel(p.words, pb.clone().lerp(pa, WORDS_AT))
    }
    // A beacon whose rows are gone fades out the same way.
    for (const [tx, p] of this.paths) if (!looks.some((l) => l.tx === tx)) p.alphaTo = p.amberTo = p.wordsTo = 0
    this.view.host.dataset.hallMoving = looks.filter((l) => l.show && l.moving).map((l) => l.tx).join(',')
    this.view.requestRender()
  }

  private path(tx: string): Path {
    let p = this.paths.get(tx)
    if (p) return p
    const mat = new LineMaterial({ color: LINK, linewidth: 2, transparent: true, opacity: 0 })
    const line = new Line2(new LineGeometry(), mat)
    line.visible = false
    this.view.scene.add(line)
    this.view.onResize((w, h) => mat.resolution.set(w, h))
    // The words stay readable from the wide hall framing, where the room's other labels step back.
    const words = this.view.addLabel('Movement on this path', new Vector3(), 'room-label--hall', true)
    words.hidden = true
    p = { line, mat, words, alpha: 0, alphaTo: 0, amber: 0, amberTo: 0, wordsAlpha: 0, wordsTo: 0 }
    this.paths.set(tx, p)
    return p
  }

  private ease(dt: number): boolean {
    let busy = false
    const quiet = new Color(LINK)
    const amber = new Color(PERSON)
    for (const p of this.paths.values()) {
      p.alpha = fade(p.alpha, p.alphaTo, dt)
      p.amber = fade(p.amber, p.amberTo, dt)
      p.wordsAlpha = fade(p.wordsAlpha, p.wordsTo, dt)
      busy ||= p.alpha !== p.alphaTo || p.amber !== p.amberTo || p.wordsAlpha !== p.wordsTo
      // Quiet: neutral, 2 px, at half strength. Moving: person blue, 3 px, nearly full.
      p.mat.color.copy(quiet).lerp(amber, p.amber)
      p.mat.linewidth = 2 + p.amber
      p.mat.opacity = p.alpha * (0.5 + 0.45 * p.amber)
      p.line.visible = p.alpha > 0
      p.words.style.opacity = String(p.wordsAlpha * p.alpha)
      p.words.hidden = p.wordsAlpha === 0
    }
    return busy
  }
}
