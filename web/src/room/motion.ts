// The screen's whole motion system. Everything that moves on the room or the panels uses these values.
//
//   out    100 ms  something leaving: a word, a label, a figure fading away
//   in     140 ms  something arriving, starting 40 ms after the old one began to leave
//   move   a critically damped spring (about 650 ms, never overshoots) for things that travel in the room:
//          the ghost between zones, the router to a new spot
//   data   300 ms  time constant for values that follow noisy 10 Hz data (link dimming, the X-ray)
//
// One CSS curve, a strong ease-out (--ease in hud.css and room.css). Opacity and transform only.
// A discrete value (a zone, "still" or "moving", which links explain the guess) changes on screen only after
// it has held for a few decisions, so one wrong decision never flickers a word, a colour or a figure.

export const MOTION = { out: 100, in: 140, inDelay: 40 } as const

/** Mirrors --ease in the CSS. */
export const EASE_CSS = 'cubic-bezier(0.23, 1, 0.32, 1)'

/** Time constants for exponential smoothing: 95% of the way in 3 x tau. */
export const TAU = {
  in: MOTION.in / 3,
  out: MOTION.out / 3,
  /** A value that follows noisy 10 Hz data: slow enough to hide the noise, fast enough to follow a walk. */
  data: 300,
} as const

/** The share of the remaining distance to cover this frame, for time constant tau (ms). */
export function follow(dtMs: number, tauMs: number): number {
  return 1 - Math.exp(-dtMs / tauMs)
}

/** Fades in at the "in" pace and out at the faster "out" pace. Returns the new value. */
export function fade(value: number, target: number, dtMs: number): number {
  const next = value + (target - value) * follow(dtMs, target > value ? TAU.in : TAU.out)
  return Math.abs(target - next) < 0.004 ? target : next
}

/** Ghost spring: 9 rad/s settles within 2% in about 650 ms (5.8 / omega) and never overshoots. */
export const GHOST_OMEGA = 9
/** How long the router takes to glide to its new spot. */
export const ROUTER_MOVE_MS = 600

/**
 * One step of a critically damped spring for one axis. Returns the new position and velocity.
 * Exact for any dt, so a slow frame on the Pi can't make it overshoot or blow up.
 */
export function springStep(x: number, v: number, target: number, omega: number, dtMs: number): [number, number] {
  const t = dtMs / 1000
  const d = x - target
  const e = Math.exp(-omega * t)
  const c = v + omega * d
  return [target + (d + c * t) * e, (v - omega * c * t) * e]
}

/** Ease-in-out for things that start and stop in place (the router moving between spots). */
export function easeInOut(t: number): number {
  const u = Math.min(1, Math.max(0, t))
  return u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2
}

/**
 * A discrete value that changes on screen only after the new value has held for `hold` ms. The classifier
 * decides every 0.1 s and is sometimes wrong for one decision; this keeps that from reaching the screen.
 * `hold` may depend on the change, e.g. quick to light a link and slower to let it go.
 */
export class Held<T> {
  private shown: T
  private next: T
  private since = 0

  constructor(
    first: T,
    private readonly hold: number | ((next: T, shown: T) => number),
  ) {
    this.shown = first
    this.next = first
  }

  get value(): T {
    return this.shown
  }

  update(value: T, nowMs: number): T {
    if (Object.is(value, this.shown)) {
      this.next = this.shown
      return this.shown
    }
    if (!Object.is(value, this.next)) {
      this.next = value
      this.since = nowMs
    }
    const hold = typeof this.hold === 'number' ? this.hold : this.hold(value, this.shown)
    if (nowMs - this.since >= hold) this.shown = value
    return this.shown
  }

  /** Shows `value` at once (the first sighting, or after the screen was cleared). */
  set(value: T) {
    this.shown = value
    this.next = value
  }
}

type V3 = [number, number, number]

/** A point that glides to a new spot with easeInOut over `ms`, starting from wherever it is now. */
export class Glide3 {
  private from: V3
  private to: V3
  private t = 1

  constructor(start: V3, private readonly ms = ROUTER_MOVE_MS) {
    this.from = [...start]
    this.to = [...start]
  }

  /** Heads for `to`. Calling it again with the same spot changes nothing. */
  set(to: V3) {
    if (to.every((v, i) => v === this.to[i])) return
    this.from = this.now()
    this.to = [...to]
    this.t = 0
  }

  /** Advances the glide. Returns true while it is still moving. */
  step(dtMs: number): boolean {
    if (this.t >= 1) return false
    this.t = Math.min(1, this.t + dtMs / this.ms)
    return true
  }

  now(): V3 {
    const k = easeInOut(this.t)
    return [0, 1, 2].map((i) => this.from[i] + (this.to[i] - this.from[i]) * k) as V3
  }
}
