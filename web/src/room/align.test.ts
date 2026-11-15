import { describe, expect, it } from 'vitest'
import { describeFit, layoutBody, nudge, tidyFit } from './align'
import { guideWordsShown, handWords, nudgePlace, placesToSave } from './guide'

describe('align mode keys', () => {
  it('moves 2 cm a press, 10 cm with Shift, east and north', () => {
    expect(nudge({}, 'ArrowRight', false)!.offset_m).toEqual([0.02, 0])
    expect(nudge({}, 'ArrowLeft', true)!.offset_m).toEqual([-0.1, 0])
    expect(nudge({ offset_m: [0.3, 0.1] }, 'ArrowUp', false)!.offset_m).toEqual([0.3, 0.12])
    expect(nudge({ offset_m: [0.3, 0.1] }, 'ArrowDown', true)!.offset_m).toEqual([0.3, 0])
  })

  it('turns left on Q and right on E: 1 degree, 15 with Shift, kept within -180..180', () => {
    expect(nudge({}, 'q', false)!.yaw_deg).toBe(1)
    expect(nudge({}, 'E', true)!.yaw_deg).toBe(-15)
    expect(nudge({ yaw_deg: 175 }, 'Q', true)!.yaw_deg).toBe(-170)
    expect(nudge({ yaw_deg: -179.5 }, 'e', false)!.yaw_deg).toBe(179.5)
  })

  it('scales by 1% and moves the cut by 5 cm, never below 20 cm', () => {
    expect(nudge({}, '+', false)!.scale).toBe(1.01)
    expect(nudge({}, '=', false)!.scale).toBe(1.01)
    expect(nudge({ scale: 1.01 }, '-', false)!.scale).toBe(1)
    expect(nudge({}, ']', false)!.cut_m).toBe(1.45)
    expect(nudge({ cut_m: 0.22 }, '[', false)!.cut_m).toBe(0.2)
  })

  it('lowers the model 2 cm on PageDown, a whole riser with Shift, and raises it on PageUp', () => {
    expect(nudge({}, 'PageDown', false)!.floor_m).toBe(0.02)
    expect(nudge({}, 'PageDown', true)!.floor_m).toBe(0.156)
    expect(nudge({ floor_m: 0.156 }, 'PageUp', false)!.floor_m).toBe(0.136)
    expect(describeFit({ floor_m: 0.312 })).toContain('Floor −0.31 m')
  })

  it('leaves other keys alone', () => {
    for (const key of ['a', 'o', 'Escape', ' ', 'Enter', 'v', 's']) expect(nudge({}, key, false)).toBeNull()
  })

  it('rounds repeated steps to readable numbers', () => {
    let fit = tidyFit({})
    for (let i = 0; i < 7; i++) fit = nudge(fit, 'ArrowRight', false)!
    expect(fit.offset_m[0]).toBe(0.14)
  })
})

describe('the saved file', () => {
  it('always has all four fields, filled from the defaults', () => {
    expect(tidyFit({})).toEqual({ offset_m: [0, 0], yaw_deg: 0, scale: 1, cut_m: 1.4, floor_m: 0 })
    expect(tidyFit({ scale: -1, yaw_deg: 540 })).toMatchObject({ scale: 1, yaw_deg: 180 })
  })

  it('reads as words on screen', () => {
    expect(describeFit({ offset_m: [0.12, -0.04], yaw_deg: 3 })).toBe(
      'East +0.12 m · North −0.04 m\nTurn +3.0° · Scale 1.000 · Cut 1.40 m · Floor +0.00 m',
    )
  })
})

describe('saving on the board (POST /layout)', () => {
  it('sends exactly the shape the board takes: room, and hall_beacons only when there are any', () => {
    expect(JSON.parse(layoutBody({ offset_m: [1.7411, -7.31] }, undefined))).toEqual({
      room: { offset_m: [1.741, -7.31], yaw_deg: 0, scale: 1, cut_m: 1.4 },
    })
    expect(Object.keys(JSON.parse(layoutBody({}, [])))).toEqual(['room'])
    // floor_m only when the square is on a tier
    expect(JSON.parse(layoutBody({ floor_m: 0 }, undefined)).room).not.toHaveProperty('floor_m')
    expect(JSON.parse(layoutBody({ floor_m: 0.312 }, undefined)).room.floor_m).toBe(0.312)
    const both = JSON.parse(layoutBody({}, [{ node: 'h', xyz_m: [3, 19, 1] }, { node: 'j', xyz_m: null }]))
    expect(both.hall_beacons).toEqual([{ node: 'h', xyz_m: [3, 19, 1] }, { node: 'j', xyz_m: null }])
  })
})

describe('the placement guide', () => {
  it('sends the devices\u2019 places to the board as nodes, only when a placement is being saved', () => {
    const places = [{ id: 'pi5b', xyz_m: [0.8, -0.38, 0.94] as [number, number, number] }]
    expect(JSON.parse(layoutBody({}, undefined, places)).nodes).toEqual([{ id: 'pi5b', xyz_m: [0.8, -0.38, 0.94] }])
    expect(JSON.parse(layoutBody({}, undefined, []))).not.toHaveProperty('nodes')
    expect(JSON.parse(layoutBody({}, undefined))).not.toHaveProperty('nodes')
  })

  it('moves a picked device 5 cm a press (Shift 20 cm), up and down too, never below the floor', () => {
    expect(nudgePlace([0.8, -0.38, 0.94], 'ArrowRight', false)).toEqual([0.85, -0.38, 0.94])
    expect(nudgePlace([0.8, -0.38, 0.94], 'ArrowDown', true)).toEqual([0.8, -0.58, 0.94])
    expect(nudgePlace([0.8, -0.38, 0.94], 'PageUp', false)).toEqual([0.8, -0.38, 0.99])
    expect(nudgePlace([0.8, -0.38, 0.03], 'PageDown', false)).toEqual([0.8, -0.38, 0])
    expect(nudgePlace([0.8, -0.38, 0.94], 'q', false)).toBeNull()
  })

  it('says where a device moved by hand is, in numbers someone can measure', () => {
    expect(handWords('Pi B', [0.85, -0.38, 0.94])).toBe('Pi B: placed by hand, 0.85 m east, -0.38 m north, 0.94 m high')
  })
})

describe('what the guide saves and says', () => {
  const marks = [
    { id: 'pi5', xyz: [0.36, 0.88, 0.8] as [number, number, number], moved: false },
    { id: 'unoq', xyz: [0.44, 0.88, 0.8] as [number, number, number], moved: false },
    { id: 'pi5b', xyz: [0.4, -0.37, 0.8] as [number, number, number], moved: false },
  ]

  it('saves nothing for places nobody chose: stepping to a desk and pressing S saves the alignment alone', () => {
    expect(placesToSave(marks)).toEqual([])
    expect(JSON.parse(layoutBody({}, undefined, placesToSave(marks)))).not.toHaveProperty('nodes')
  })

  it('saves only the devices moved by hand', () => {
    const moved = marks.map((m) => (m.id === 'pi5b' ? { ...m, xyz: [0.4, -0.2, 0.75] as [number, number, number], moved: true } : m))
    expect(placesToSave(moved)).toEqual([{ id: 'pi5b', xyz_m: [0.4, -0.2, 0.75] }])
    expect(JSON.parse(layoutBody({}, undefined, placesToSave(moved))).nodes).toEqual([{ id: 'pi5b', xyz_m: [0.4, -0.2, 0.75] }])
  })

  it('saves the guide\u2019s own places only once they were taken with Enter', () => {
    expect(placesToSave(marks.map((m) => ({ ...m, taken: false })))).toEqual([])
    const taken = placesToSave(marks.map((m) => ({ ...m, taken: true })))
    expect(taken.map((p) => p.id)).toEqual(['pi5', 'unoq', 'pi5b'])
    expect(taken[2].xyz_m).toEqual([0.4, -0.37, 0.8])
    expect(JSON.parse(layoutBody({}, undefined, taken)).nodes).toHaveLength(3)
  })

  it('leaves the words off a box that sits on or right beside its device, and shows them once it is moved away', () => {
    expect(guideWordsShown([0.36, 0.88, 0.8], [0.36, 0.8, 0.75])).toBe(false) // 9 cm from Pi A as drawn
    expect(guideWordsShown([0.4, -0.37, 0.8], [0.4, -0.2, 0.75])).toBe(false) // 18 cm from Pi B as drawn
    expect(guideWordsShown([0.4, -0.6, 0.8], [0.4, -0.2, 0.75])).toBe(true)
    expect(guideWordsShown([0.4, -0.37, 0.8], null)).toBe(true) // a device the layout doesn't draw
  })
})
