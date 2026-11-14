import { describe, expect, it } from 'vitest'
import { FpsTally } from './fps'
import { viewOptions } from './view'

describe('fps meter', () => {
  it('skips the warm-up second, then keeps the running min and average', () => {
    const t = new FpsTally()
    expect(t.add(12)).toBeNull()
    expect(t.add(60)).toEqual({ now: 60, min: 60, avg: 60, seconds: 1 })
    expect(t.add(40)).toEqual({ now: 40, min: 40, avg: 50, seconds: 2 })
  })
})

describe('view options from the URL', () => {
  const PI = 'V3D 7.1.10.2'
  const MAC = 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)'

  it('keeps what kept the Pi 5 GPU at about 40% busy on a Pi: no antialiasing, pixel ratio 1', () => {
    expect(viewOptions(new URLSearchParams(''), PI, 1)).toEqual({ quality: 'pi', antialias: false, pixelRatio: 1 })
    expect(viewOptions(new URLSearchParams(''), `ANGLE (Broadcom, ${PI}, OpenGL ES 3.1)`, 1).quality).toBe('pi')
  })

  it("goes hi anywhere else: antialiasing and the display's pixel ratio, up to 2", () => {
    expect(viewOptions(new URLSearchParams(''), MAC, 2)).toEqual({ quality: 'hi', antialias: true, pixelRatio: 2 })
    expect(viewOptions(new URLSearchParams(''), MAC, 3).pixelRatio).toBe(2)
    expect(viewOptions(new URLSearchParams(''), '', 1).quality).toBe('hi')
  })

  it('lets ?q= pick the quality, and ?aa= and ?dpr= override it', () => {
    expect(viewOptions(new URLSearchParams('q=pi'), MAC, 2)).toEqual({ quality: 'pi', antialias: false, pixelRatio: 1 })
    expect(viewOptions(new URLSearchParams('q=hi'), PI, 1).quality).toBe('hi')
    expect(viewOptions(new URLSearchParams('aa=1&dpr=2'), PI, 1)).toEqual({ quality: 'pi', antialias: true, pixelRatio: 2 })
    expect(viewOptions(new URLSearchParams('aa=0'), MAC, 2).antialias).toBe(false)
    expect(viewOptions(new URLSearchParams('dpr=0.75'), MAC, 2).pixelRatio).toBe(0.75)
    expect(viewOptions(new URLSearchParams('dpr=nope'), PI, 1).pixelRatio).toBe(1)
    expect(viewOptions(new URLSearchParams('dpr=9'), PI, 1).pixelRatio).toBe(1)
  })
})
