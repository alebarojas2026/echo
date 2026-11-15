import { Box3, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { FIRST_LOOK_MS, FLY_MS, Fly, HALL_CAPTION, cutaway, hallShot, hallWordsAlpha, mixShot, pinnedFraming, wideness } from './fly'
import { roomShot, type RoomView, type Shot } from './view'

/** Just enough of RoomView for the fly: it records the shots and lets the test run frames. */
function fakeView() {
  const animators: ((dt: number) => boolean)[] = []
  const view = {
    shots: [] as Shot[],
    size: [1280, 1080] as [number, number],
    host: { dataset: {} as Record<string, string> },
    addAnimator: (fn: (dt: number) => boolean) => void animators.push(fn),
    setShot: (s: Shot | ((w: number, h: number) => Shot)) => void view.shots.push(typeof s === 'function' ? s(...view.size) : s),
    requestRender: () => {},
    /** Runs frames of `dt` ms for `ms`. */
    run(ms: number, dt = 16) {
      for (let t = 0; t < ms; t += dt) animators.forEach((fn) => fn(dt))
    },
    get shot() {
      return view.shots.at(-1)!
    },
  }
  return view
}

const HALL = new Box3(new Vector3(-12, -0.03, -20), new Vector3(18, 6, 10))

describe('the hall framing', () => {
  it('looks at the middle of the hall and is far wider than the square', () => {
    const hall = hallShot(HALL, 12)
    expect(hall.target.x).toBeCloseTo(3)
    expect(hall.target.z).toBeCloseTo(-5)
    expect(hall.radiusM).toBeGreaterThan(10 * roomShot().radiusM)
    expect(hall.elevDeg).toBeLessThan(roomShot().elevDeg)
  })

  it('never frames tighter than twice the square, even for a tiny scan', () => {
    const tiny = hallShot(new Box3(new Vector3(-1, 0, -1), new Vector3(1, 1, 1)), 1.4)
    expect(tiny.radiusM).toBeCloseTo(2 * roomShot().radiusM)
  })
})

describe('flying between shots', () => {
  const square = roomShot()
  const hall = hallShot(HALL, 12)

  it('starts and ends exactly on the two shots', () => {
    expect(mixShot(square, hall, 0)).toEqual(square)
    const end = mixShot(square, hall, 1)
    expect(end.radiusM).toBeCloseTo(hall.radiusM)
    expect(end.target.distanceTo(hall.target)).toBeCloseTo(0)
  })

  it('zooms by ratio, so halfway is the geometric middle of the two sizes', () => {
    expect(mixShot(square, hall, 0.5).radiusM).toBeCloseTo(Math.sqrt(square.radiusM * hall.radiusM))
    expect(wideness(mixShot(square, hall, 0.5), square, hall)).toBeCloseTo(0.5)
    expect(wideness(square, square, hall)).toBe(0)
    expect(wideness(hall, square, hall)).toBe(1)
  })

  it('reads ?view=', () => {
    expect(pinnedFraming(new URLSearchParams('view=hall'))).toBe('hall')
    expect(pinnedFraming(new URLSearchParams('view=square'))).toBe('square')
    expect(pinnedFraming(new URLSearchParams('view=top'))).toBeNull()
  })
})

describe('the hall view\u2019s caption', () => {
  it('says the hall is a model built from a scan and that the board draws only the live marks', () => {
    expect([...HALL_CAPTION]).toEqual(['Hall model built from a scan, not by the board.', 'The board draws the live marks.'])
    // Nothing about when it was made: it was built during the event, so "before the event" would not be true.
    expect(HALL_CAPTION.join(' ')).not.toMatch(/before/i)
  })

  it('shows in the hall view, fades with the fly, and is gone in the desk view', () => {
    expect(hallWordsAlpha(1)).toBe(1)
    expect(hallWordsAlpha(0.75)).toBeCloseTo(0.5)
    expect(hallWordsAlpha(0.5)).toBe(0)
    expect(hallWordsAlpha(0)).toBe(0)
  })
})

describe('the see-through row', () => {
  it('stays solid until the camera is nearly down, then opens smoothly: never a slot seen from far away', () => {
    expect(cutaway(1)).toBe(0)
    expect(cutaway(0.5)).toBe(0)
    expect(cutaway(0.3)).toBe(0)
    expect(cutaway(0.15)).toBeCloseTo(0.5)
    expect(cutaway(0)).toBe(1)
    for (let w = 0; w < 0.3; w += 0.01) expect(cutaway(w)).toBeGreaterThan(cutaway(w + 0.01))
  })
})

describe('the fly', () => {
  const hall = hallShot(HALL, 12)
  const square = roomShot().radiusM

  it('on load shows the hall, takes a moment, then flies down to the square', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.setHall(hall)
    expect(view.shot.radiusM).toBeCloseTo(hall.radiusM)
    expect(view.host.dataset.view).toBe('hall')
    view.run(FIRST_LOOK_MS - 100)
    expect(fly.wide).toBe(1) // still taking it in
    expect(FIRST_LOOK_MS + FLY_MS).toBe(3000) // from the whole hall to the desk in 3 s
    view.run(1200 + FLY_MS)
    expect(view.shot.radiusM).toBeCloseTo(square)
    expect(view.host.dataset.view).toBe('square')
  })

  it('lands exactly: on a laptop\'s canvas too, the view says square and nothing of the hall stays faded in', () => {
    const sizes: [number, number][] = []
    for (let w = 640; w <= 1600; w += 61) for (let h = 600; h <= 1200; h += 97) sizes.push([w, h])
    for (const size of sizes) {
      const view = fakeView()
      view.size = size
      const fly = new Fly(view as unknown as RoomView, null, () => {})
      fly.setHall(hall)
      view.run(1200 + FLY_MS + 100)
      expect(fly.wide).toBe(0)
      expect(view.host.dataset.view).toBe('square')
    }
  })

  it('lands on the close framing it is given (in situ inside the hall) and follows the canvas from then on', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    const situ = (w: number): Shot => ({ elevDeg: 45, target: new Vector3(0, 0.8, 0.3), radiusM: 1.7 * Math.min(1, w / 1280) })
    fly.setClose(situ)
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 100)
    expect(view.shot).toEqual(situ(1280))
    expect(fly.wide).toBe(0)
    view.size = [800, 900]
    fly.toggle()
    view.run(FLY_MS + 100)
    fly.toggle()
    view.run(FLY_MS + 100)
    expect(view.shot.radiusM).toBeCloseTo(situ(800).radiusM)
  })

  it('never jumps: every frame of the fly is a small step from the one before', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 100)
    for (let i = 1; i < view.shots.length; i++) {
      const ratio = view.shots[i].radiusM / view.shots[i - 1].radiusM
      expect(Math.abs(Math.log(ratio))).toBeLessThan(0.05)
    }
  })

  it('on reset goes out to the hall, pauses, and comes back', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 100)
    fly.reset()
    view.run(FLY_MS + 100)
    expect(fly.wide).toBe(1)
    view.run(1500)
    expect(fly.wide).toBe(1) // the pause
    view.run(500 + FLY_MS + 100)
    expect(fly.wide).toBe(0)
  })

  it('on H turns around mid-flight from where it is, without a jump', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.setHall(hall)
    view.run(1200 + FLY_MS / 2)
    const before = view.shot.radiusM
    fly.toggle() // was heading to the square: back out to the hall
    view.run(16)
    expect(Math.abs(Math.log(view.shot.radiusM / before))).toBeLessThan(0.05)
    view.run(FLY_MS + 100)
    expect(fly.wide).toBe(1)
  })

  it('stays on a pinned framing: no fly on load, none on reset', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, 'hall', () => {})
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 100)
    expect(fly.wide).toBe(1)
    fly.reset()
    view.run(FLY_MS)
    expect(fly.wide).toBe(1)
  })

  it('rests on the hall while the arrival screen waits, drifting, then flies down on found without a jump', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.hold() // "waiting" can come before the hall model has loaded
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 500)
    expect(fly.wide).toBe(1) // no fly down while waiting
    const xs = view.shots.slice(-50).map((s) => s.target.x)
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(0.01) // drifting
    expect(Math.max(...xs.map((x) => Math.abs(x - hall.target.x)))).toBeLessThanOrEqual(1.5)
    const before = view.shot.target.clone()
    fly.arrive()
    view.run(16)
    expect(view.shot.target.distanceTo(before)).toBeLessThan(0.2) // starts from where the drift was
    view.run(FLY_MS + 100)
    expect(fly.wide).toBe(0)
    expect(view.host.dataset.view).toBe('square')
  })

  it('stays at the desk when the hall model loads after someone was found, and keeps the hall for later', () => {
    for (const close of [roomShot, (w: number, h: number) => ({ ...roomShot(w, h), elevDeg: 45, target: roomShot(w, h).target.clone().add(new Vector3(0.2, 0.3, 0)) })]) {
      const view = fakeView()
      const wides: number[] = []
      const fly = new Fly(view as unknown as RoomView, null, (w) => wides.push(w))
      fly.hold() // the arrival screen, before the model is in
      fly.arrive() // found: the camera is at the desk
      view.run(3000)
      fly.setClose(close)
      const before = view.shots.length
      fly.setHall(hall) // the model arrives seconds into the visit
      view.run(FLY_MS + 100)
      expect(Math.max(0, ...wides)).toBeLessThan(0.05) // never out to the hall
      const shots = view.shots.slice(before)
      expect(shots.every((s) => s.radiusM < hall.radiusM / 2)).toBe(true)
      const steps = shots.slice(1).map((s, i) => s.target.distanceTo(shots[i].target))
      expect(Math.max(0, ...steps)).toBeLessThan(0.05) // and to the new close framing by a glide, not a jump
      expect(view.shot.target.distanceTo(close(...view.size).target)).toBeLessThan(1e-6)
      expect(fly.wide).toBe(0)
      expect(view.host.dataset.view).toBe('square')
      fly.reset() // the hall was kept: between judges the camera still goes out to it
      view.run(FLY_MS + 100)
      expect(fly.wide).toBe(1)
    }
  })

  it('still shows the hall first when the model loads while the arrival screen waits or was never up', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.arrive() // nothing was waiting (the page's first call, with no arrival state yet)
    fly.setHall(hall)
    expect(fly.wide).toBe(1)
    const next = fakeView()
    const again = new Fly(next as unknown as RoomView, null, () => {})
    again.hold()
    again.arrive()
    again.hold() // the person left before the model was in: waiting again
    again.setHall(hall)
    next.run(FIRST_LOOK_MS + FLY_MS + 100)
    expect(again.wide).toBe(1)
  })

  it('goes back to the hall when waiting starts again, and ignores found when nothing was waiting', () => {
    const view = fakeView()
    const fly = new Fly(view as unknown as RoomView, null, () => {})
    fly.setHall(hall)
    view.run(1200 + FLY_MS + 100)
    fly.arrive() // nothing was waiting: stays on the square
    view.run(500)
    expect(fly.wide).toBe(0)
    fly.hold() // the next visitor's arrival screen
    view.run(16)
    expect(fly.wide).toBe(1)
  })
})
