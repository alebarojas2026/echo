import { Box3, BoxGeometry, Mesh, MeshBasicMaterial, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { SQUARE_M } from './frame'
import { easeInOut } from './motion'
import { PERSON, SQUARE } from './palette'
import { roomShot, type RoomView, type Shot } from './view'

// Two framings of the same scene: "hall", the whole scanned judging hall with the square small in it, and
// "square", the room's normal framing. The camera flies between them calmly (ease in-out, about 3 s) and stays
// north-up all the way:
//   on load    hall, a moment to take it in, then down to the square
//   on reset   out to the hall, a pause, and back (the brain's reset event, between judges)
//   on H       to the other framing, for the presenter
// ?view=hall or ?view=square pins one framing (H still works). Under reduced motion the camera cuts instead.
// While wide, the labels fade out (they would pile up on a square 60 px across), the square gets a
// pixel-width outline, and an amber column stands over the figure so the person still reads from the back row.

export type Framing = 'hall' | 'square'

export const FLY_MS = 3000
/** On load, how long the hall shows before the camera flies down. */
const FIRST_LOOK_MS = 1200
/** On reset, how long the camera stays on the hall before flying back. */
const RESET_HOLD_MS = 2000
const HALL_ELEV_DEG = 40
/** The hall's floor plan fills a little more than the view, so empty corners don't shrink it. */
const HALL_FILL = 0.85

/** The whole hall, north up: looks at the middle of its floor plan (up to the cut) and fits its half-diagonal. */
export function hallShot(bounds: Box3, cutM: number): Shot {
  const top = Math.min(bounds.max.y, cutM)
  const target = new Vector3((bounds.min.x + bounds.max.x) / 2, Math.max(0, top / 4), (bounds.min.z + bounds.max.z) / 2)
  const half = Math.hypot(bounds.max.x - bounds.min.x, bounds.max.z - bounds.min.z) / 2
  const square = roomShot().radiusM
  return { elevDeg: HALL_ELEV_DEG, target, radiusM: Math.max(square * 2, half * HALL_FILL) }
}

/** The shot `u` (0..1) of the way from a to b: angle and target in a straight line, size by ratio so the zoom
 *  feels even from start to end. */
export function mixShot(a: Shot, b: Shot, u: number): Shot {
  return {
    elevDeg: a.elevDeg + (b.elevDeg - a.elevDeg) * u,
    target: a.target.clone().lerp(b.target, u),
    radiusM: a.radiusM * (b.radiusM / a.radiusM) ** u,
  }
}

/** How wide `shot` is: 0 at the square's framing, 1 at the hall's, by zoom. */
export function wideness(shot: Shot, square: Shot, hall: Shot): number {
  const span = Math.log(hall.radiusM / square.radiusM)
  if (span <= 0) return 0
  return Math.min(1, Math.max(0, Math.log(shot.radiusM / square.radiusM) / span))
}

/** ?view=hall or ?view=square, else null. */
export function pinnedFraming(params: URLSearchParams): Framing | null {
  const v = params.get('view')
  return v === 'hall' || v === 'square' ? v : null
}

interface Leg {
  to: Framing
  /** Waits this long on the current shot before setting off. */
  waitMs: number
}

export class Fly {
  /** 0 at the square's framing, 1 at the hall's. */
  wide = 0
  private readonly square = roomShot()
  private hall: Shot | null = null
  private shot = this.square
  private framing: Framing = 'square'
  private legs: Leg[] = []
  private from: Shot = this.square
  private elapsed = 0
  private readonly reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

  constructor(
    private readonly view: RoomView,
    private readonly pinned: Framing | null,
    private readonly onWide: (wide: number) => void,
  ) {
    view.addAnimator((dt) => this.step(dt))
  }

  /** The hall is known (its scan has loaded): show it, then fly down unless a framing is pinned. */
  setHall(hall: Shot) {
    this.hall = hall
    if (this.pinned) return this.cut(this.pinned)
    this.cut('hall')
    this.legs = this.reduced ? [{ to: 'square', waitMs: 0 }] : [{ to: 'square', waitMs: FIRST_LOOK_MS }]
    this.begin()
  }

  /** Between judges: out to the hall, a pause, and back. Not when pinned or under reduced motion. */
  reset() {
    if (!this.hall || this.pinned || this.reduced) return
    this.legs = [
      { to: 'hall', waitMs: 0 },
      { to: 'square', waitMs: RESET_HOLD_MS },
    ]
    this.begin()
  }

  /** H: to the other framing, from wherever the camera is now. */
  toggle() {
    if (!this.hall) return
    const heading = this.legs.at(-1)?.to ?? this.framing
    this.legs = [{ to: heading === 'hall' ? 'square' : 'hall', waitMs: 0 }]
    this.begin()
  }

  private shotOf(framing: Framing): Shot {
    return framing === 'hall' && this.hall ? this.hall : this.square
  }

  private cut(framing: Framing) {
    this.framing = framing
    this.legs = []
    this.show(this.shotOf(framing))
  }

  /** Starts the first leg from the shot on screen now, so a fly that interrupts another never jumps. */
  private begin() {
    this.from = this.shot
    this.elapsed = 0
    if (this.reduced) {
      const last = this.legs.at(-1)
      if (last) this.cut(last.to)
    }
    this.view.requestRender()
  }

  private show(shot: Shot) {
    this.shot = shot
    this.view.setShot(shot)
    this.wide = this.hall ? wideness(shot, this.square, this.hall) : 0
    this.view.host.dataset.view = this.wide >= 1 ? 'hall' : this.wide <= 0 ? 'square' : 'flying'
    this.onWide(this.wide)
  }

  private step(dt: number): boolean {
    const leg = this.legs[0]
    if (!leg) return false
    this.elapsed += dt
    const u = (this.elapsed - leg.waitMs) / FLY_MS
    if (u <= 0) return true
    this.show(mixShot(this.from, this.shotOf(leg.to), easeInOut(u)))
    if (u < 1) return true
    this.framing = leg.to
    this.legs.shift()
    this.from = this.shot
    this.elapsed = 0
    return this.legs.length > 0
  }
}

const COLUMN_M = 2.4
const COLUMN_PX = 6

/** The marks that keep the square and the person readable from the hall framing. */
export class HallMarks {
  private readonly outline: Line2
  private readonly column: Mesh<BoxGeometry, MeshBasicMaterial>
  private readonly scratch = new Vector3()

  constructor(
    private readonly view: RoomView,
    private readonly fly: Fly,
    private readonly standing: () => { at: Vector3; alpha: number },
  ) {
    const h = SQUARE_M / 2
    const geometry = new LineGeometry()
    geometry.setPositions([-h, 0.01, -h, h, 0.01, -h, h, 0.01, h, -h, 0.01, h, -h, 0.01, -h])
    const lineMat = new LineMaterial({ color: SQUARE, linewidth: 3, transparent: true, opacity: 0, depthTest: false })
    this.outline = new Line2(geometry, lineMat)
    this.outline.renderOrder = 20
    view.onResize((w, height) => lineMat.resolution.set(w, height))

    const box = new BoxGeometry(1, 1, 1).translate(0, 0.5, 0) // stands on the floor
    this.column = new Mesh(box, new MeshBasicMaterial({ color: PERSON, transparent: true, opacity: 0, depthTest: false, depthWrite: false }))
    this.column.renderOrder = 21
    this.outline.visible = this.column.visible = false
    view.scene.add(this.outline, this.column)
    // Runs every frame something else moves (the figure, the fly); never asks for frames itself.
    view.addAnimator(() => {
      this.place()
      return false
    })
  }

  private place() {
    const wide = this.fly.wide
    this.outline.material.opacity = wide
    this.outline.visible = wide > 0
    const { at, alpha } = this.standing()
    const cam = this.view.camera
    this.column.material.opacity = 0.9 * wide * alpha
    this.column.visible = this.column.material.opacity > 0
    if (!this.column.visible) return
    // A fixed width on screen: metres per pixel at the column's distance from the camera.
    const dist = cam.position.distanceTo(this.scratch.copy(at))
    const perPx = (2 * dist * Math.tan((cam.fov * Math.PI) / 360)) / Math.max(1, this.view.renderer.domElement.clientHeight)
    const width = COLUMN_PX * perPx
    this.column.position.set(at.x, 0, at.z)
    this.column.scale.set(width, COLUMN_M, width)
  }
}
