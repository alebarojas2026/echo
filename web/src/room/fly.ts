import { Box3, BoxGeometry, Mesh, MeshBasicMaterial, Vector3 } from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { SIZE_M } from './frame'
import { easeInOut } from './motion'
import { PERSON, SQUARE } from './palette'
import { roomShot, type RoomView, type Shot, type ShotFor } from './view'

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

export const FLY_MS = 2500
/** On load, how long the hall shows before the camera flies down: with the fly, 3 s from the hall to the desk. */
export const FIRST_LOOK_MS = 500
/** On reset, how long the camera stays on the hall before flying back. */
const RESET_HOLD_MS = 2000
/** While the arrival screen waits (#552), the hall shot drifts east and west this far, about once a minute. */
const DRIFT_M = 1.5
const DRIFT_PERIOD_MS = 60_000
const HALL_ELEV_DEG = 40
/** The hall's floor plan fills a little more than the view, so empty corners don't shrink it. */
const HALL_FILL = 0.8

/**
 * The whole hall: looks at the middle of its floor plan (up to the cut) and fits its half-diagonal. Seen from due
 * south of the layout, north up, unless the hall lies on its side there: `yawDeg` is how far the hall's model is
 * turned to stand the layout at its desk (room.json), and with the layout at a row's end the layout's north runs
 * along the row, a quarter turn from the hall's. Then the camera goes round with the hall, so the hall is seen
 * the right way up, its front at the top. A hall turned a little (a desk on the curve of its row) or right round
 * (the layout in front of a desk, seen from the stage side) is left as it was.
 */
export function hallShot(bounds: Box3, cutM: number, yawDeg = 0): Shot {
  const top = Math.min(bounds.max.y, cutM)
  const target = new Vector3((bounds.min.x + bounds.max.x) / 2, Math.max(0, top / 4), (bounds.min.z + bounds.max.z) / 2)
  const half = Math.hypot(bounds.max.x - bounds.min.x, bounds.max.z - bounds.min.z) / 2
  const square = roomShot().radiusM
  const onItsSide = Math.abs(yawDeg) > 45 && Math.abs(yawDeg) < 135
  return { elevDeg: HALL_ELEV_DEG, ...(onItsSide ? { azimDeg: yawDeg } : {}), target, radiusM: Math.max(square * 2, half * HALL_FILL) }
}

/** The shot `u` (0..1) of the way from a to b: angle and target in a straight line, size by ratio so the zoom
 *  feels even from start to end. */
export function mixShot(a: Shot, b: Shot, u: number): Shot {
  return {
    elevDeg: a.elevDeg + (b.elevDeg - a.elevDeg) * u,
    // Only a shot that is turned carries a turn: every other shot stays as it was.
    ...(a.azimDeg || b.azimDeg ? { azimDeg: (a.azimDeg ?? 0) + ((b.azimDeg ?? 0) - (a.azimDeg ?? 0)) * u } : {}),
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

/** How see-through the row in front of the strip is (0 solid, 1 fully) for how wide the camera is: solid until the
 *  camera is nearly down, then fading in smoothly over the last part of the move. Opened sooner, it showed as a
 *  dark slot in the row from far away. */
export function cutaway(wide: number): number {
  const u = Math.min(1, Math.max(0, 1 - wide / CUTAWAY_FROM))
  return u * u * (3 - 2 * u)
}
const CUTAWAY_FROM = 0.3

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
  private hall: Shot | null = null
  private shot: Shot
  private framing: Framing = 'square'
  private legs: Leg[] = []
  private from: Shot
  private elapsed = 0
  /** The close framing the camera lands on: the room's own, or in situ inside the hall (setClose). */
  private close: ShotFor = roomShot
  /** The arrival screen is up ("Nobody is here."): rest on the hall, drifting, until it says found. */
  private holding = false
  /** Someone was found while the hall model was still loading: the camera is at the desk and stays there. */
  private foundEarly = false
  private driftMs = 0
  private readonly reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches

  constructor(
    private readonly view: RoomView,
    private readonly pinned: Framing | null,
    private readonly onWide: (wide: number) => void,
  ) {
    this.shot = this.from = this.square()
    view.addAnimator((dt) => this.step(dt))
  }

  /** The close framing for the canvas as it is now (a narrow canvas backs off to keep the side words on it). */
  private square(): Shot {
    return this.close(...this.view.size)
  }

  /** The framing to land on from now on (in situ once the hall model is known). Call before setHall. */
  setClose(close: ShotFor) {
    this.close = close
  }

  /** The hall is known (its scan has loaded): show it, then fly down unless a framing is pinned or the arrival
   *  screen is waiting (then it rests on the hall until arrive()). A model that loads after someone was found (it
   *  is a few MB over the hotspot) never pulls the camera off them: the hall is kept for the next reset or hold,
   *  and the camera only glides to the close framing it was given for the hall. */
  setHall(hall: Shot) {
    this.hall = hall
    if (this.pinned) return this.cut(this.pinned)
    if (this.foundEarly) {
      this.foundEarly = false
      this.legs = [{ to: 'square', waitMs: 0 }]
      return this.begin()
    }
    this.cut('hall')
    if (this.holding) return
    this.legs = this.reduced ? [{ to: 'square', waitMs: 0 }] : [{ to: 'square', waitMs: FIRST_LOOK_MS }]
    this.begin()
  }

  /** The arrival screen is up (#552 "waiting"): rest on the whole hall, drifting very slowly, until arrive(). */
  hold() {
    this.holding = true
    this.foundEarly = false
    this.driftMs = 0
    if (this.hall && !this.pinned) this.cut('hall')
    this.view.requestRender()
  }

  /** Someone was found, or the arrival screen closed: fly from wherever the camera is down to the floor. */
  arrive() {
    if (!this.holding) return
    this.holding = false
    this.foundEarly = !this.hall
    if (!this.hall || this.pinned) return
    this.legs = [{ to: 'square', waitMs: 0 }]
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

  /** The close framing changed under the camera (room kept free for a bar over the room's bottom): glide to it.
   *  Nothing to do while the camera is on the hall or heading there; it lands on the new framing when it comes
   *  down. */
  refit() {
    const heading = this.legs.at(-1)?.to ?? this.framing
    if (heading !== 'square' || this.pinned === 'hall') return
    this.legs = [{ to: 'square', waitMs: 0 }]
    this.begin()
  }

  /**
   * Finishes whatever move is under way or queued, at once: the camera is put where it was heading. For a tab that
   * was hidden (no frames ran, so a fly made no progress): when it is looked at again it shows where things are
   * now, not the start of a fly that should have ended long ago. Nothing to do when nothing is queued.
   */
  settle() {
    const last = this.legs.at(-1)
    if (!last) return
    this.cut(last.to)
    this.from = this.shot
    this.elapsed = 0
    this.view.requestRender()
  }

  /** H: to the other framing, from wherever the camera is now. */
  toggle() {
    if (!this.hall) return
    const heading = this.legs.at(-1)?.to ?? this.framing
    this.legs = [{ to: heading === 'hall' ? 'square' : 'hall', waitMs: 0 }]
    this.begin()
  }

  private shotOf(framing: Framing): Shot {
    return framing === 'hall' && this.hall ? this.hall : this.square()
  }

  private cut(framing: Framing) {
    this.framing = framing
    this.legs = []
    this.show(this.shotOf(framing), framing)
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

  /** Puts the camera on `shot`. Once it has arrived on the square, the view follows the canvas size from then on. */
  private show(shot: Shot, arrived?: Framing) {
    this.shot = shot
    this.view.setShot(arrived === 'square' ? this.close : shot)
    // Arrived is exact: the last step's shot can sit a rounding error off the square's, which would read as "flying".
    this.wide = !this.hall || arrived === 'square' ? 0 : arrived === 'hall' ? 1 : wideness(shot, this.square(), this.hall)
    this.view.host.dataset.view = this.wide >= 1 ? 'hall' : this.wide <= 0 ? 'square' : 'flying'
    this.onWide(this.wide)
  }

  private step(dt: number): boolean {
    const leg = this.legs[0]
    if (!leg) return this.drift(dt)
    this.elapsed += dt
    const u = (this.elapsed - leg.waitMs) / FLY_MS
    if (u <= 0) return true
    this.show(mixShot(this.from, this.shotOf(leg.to), easeInOut(u)), u >= 1 ? leg.to : undefined)
    if (u < 1) return true
    this.framing = leg.to
    this.legs.shift()
    this.from = this.shot
    this.elapsed = 0
    return this.legs.length > 0
  }

  /** While the arrival screen waits: the hall shot glides east and west, about once a minute, north up throughout.
   *  Not when pinned or under reduced motion. Returns true while it drifts (the room keeps drawing). */
  private drift(dt: number): boolean {
    if (!this.holding || !this.hall || this.pinned || this.reduced) return false
    this.driftMs += dt
    const x = DRIFT_M * Math.sin((2 * Math.PI * this.driftMs) / DRIFT_PERIOD_MS)
    this.show({ ...this.hall, target: this.hall.target.clone().add(new Vector3(x, 0, 0)) })
    return true
  }
}

const COLUMN_M = 3
const COLUMN_PX = 8
/** "Our desk" stands this far above the floor, clear of the column's top. */
const DESK_WORD_M = 3.9

/**
 * What the hall view says about the hall itself, one sentence a line. The hall is a detailed model next to
 * "everything runs on the board": a judge can fairly ask who made it. It was built from a scan of the room, on
 * another machine; the board draws only the live marks on it.
 */
export const HALL_CAPTION = ['Hall model built from a scan, not by the board.', 'The board draws the live marks.'] as const

/** How strongly the hall view's own words show for how wide the camera is: only in the wide half of the fly, and
 *  gone by the time the desk is what is on screen. */
export function hallWordsAlpha(wide: number): number {
  return Math.min(1, Math.max(0, (wide - 0.5) / 0.5))
}

/** How long pred must have said a person is present, without a break, before the room comes down by itself. */
export const SELF_ARRIVE_MS = 4000

/** How long a person has been present without a break, on the board's own clock (the states' t), so a page whose
 *  timers are slowed (a hidden tab) still counts right. A state that says nobody starts the count again. */
export class PresentRun {
  private since: number | null = null
  private last = 0

  /** Takes one state: whether it says a person is present, and its t. Returns the run so far, ms. */
  update(person: boolean, t: number): number {
    if (!person) this.since = null
    else this.since ??= t
    this.last = this.since === null ? 0 : Math.max(0, t - this.since)
    return this.last
  }

  get ms(): number {
    return this.last
  }
}

/**
 * The room's own way down from the hall, as a safety net: the walk-up card still says it is waiting, but the
 * board has said a person is present for 4 s. The card is the panels' and decides the words; the room does not
 * leave a person who is standing there looking at a dimmed, empty hall because the card did not yield.
 */
export function comesDownAlone(card: string | undefined, presentMs: number): boolean {
  return card === 'waiting' && presentMs >= SELF_ARRIVE_MS
}

/** The marks that keep the square and the person readable from the hall framing. */
export class HallMarks {
  private readonly outline: Line2
  private readonly column: Mesh<BoxGeometry, MeshBasicMaterial>
  /** Says where we are in the whole hall, where the layout is a few pixels across. */
  private readonly word: HTMLElement
  /** HALL_CAPTION, in the room's bottom-left corner while the hall is on screen. */
  private readonly caption: HTMLElement
  private readonly scratch = new Vector3()

  constructor(
    private readonly view: RoomView,
    private readonly fly: Fly,
    private readonly standing: () => { at: Vector3; alpha: number },
  ) {
    const hx = SIZE_M[0] / 2
    const hz = SIZE_M[1] / 2
    const geometry = new LineGeometry()
    geometry.setPositions([-hx, 0.01, -hz, hx, 0.01, -hz, hx, 0.01, hz, -hx, 0.01, hz, -hx, 0.01, -hz])
    const lineMat = new LineMaterial({ color: SQUARE, linewidth: 3, transparent: true, opacity: 0, depthTest: false })
    this.outline = new Line2(geometry, lineMat)
    this.outline.renderOrder = 20
    view.onResize((w, height) => lineMat.resolution.set(w, height))

    const box = new BoxGeometry(1, 1, 1).translate(0, 0.5, 0) // stands on the floor
    this.column = new Mesh(box, new MeshBasicMaterial({ color: PERSON, transparent: true, opacity: 0, depthTest: false, depthWrite: false }))
    this.column.renderOrder = 21
    this.outline.visible = this.column.visible = false
    view.scene.add(this.outline, this.column)
    this.word = view.addLabel('Our desk', new Vector3(0, DESK_WORD_M, 0), 'room-label--ourdesk', true)
    this.word.hidden = true
    this.caption = document.createElement('p')
    this.caption.className = 'room-hall-caption'
    for (const line of HALL_CAPTION) this.caption.append(Object.assign(document.createElement('span'), { textContent: line }))
    this.caption.hidden = true
    view.host.append(this.caption)
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
    // Only in the wide half of the fly: closer in, the figure itself reads, and a pole through it would not.
    const far = hallWordsAlpha(wide)
    this.word.hidden = this.caption.hidden = far === 0
    this.word.style.opacity = this.caption.style.opacity = String(far)
    this.column.material.opacity = 0.9 * alpha * far
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
