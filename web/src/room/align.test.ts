import { describe, expect, it } from 'vitest'
import { describeFit, layoutBody, nudge, tidyFit } from './align'

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
