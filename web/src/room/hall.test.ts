import { describe, expect, it } from 'vitest'
import type { HallLink } from './contract'
import { applyLayout } from './frame'
import { pathLooks } from './hall'
import { DESK_LAYOUT } from './layouts.fixture'

const row = (tx: string, rx: string, over: Partial<HallLink> = {}): HallLink => ({
  id: `${tx}>${rx}:ble`, tx, rx, xy_m: [3, 19], activity: 0.1, moving: false, rate_hz: 6.5, stale: false, ...over,
})

describe('hall paths', () => {
  it('draw nothing when the state has no hall links', () => {
    expect(pathLooks(undefined)).toEqual([])
    expect(pathLooks([])).toEqual([])
  })

  it('draw one line per beacon, to the board when the board hears it, amber when any of its links is moving', () => {
    const [h] = pathLooks([row('h', 'pi5'), row('h', 'unoq', { moving: true })])
    expect(h).toEqual({ tx: 'h', show: true, moving: true, xy: [3, 19], rx: 'unoq' })
    expect(pathLooks([row('h', 'unoq'), row('h', 'pi5')])[0].moving).toBe(false)
  })

  it('follow the brain\'s moving, never a threshold of their own on activity', () => {
    expect(pathLooks([row('h', 'unoq', { activity: 0.95, moving: false })])[0].moving).toBe(false)
    expect(pathLooks([row('h', 'unoq', { activity: 0.05, moving: true })])[0].moving).toBe(true)
  })

  it('leave out a stale path, or one with no spot, without any fault', () => {
    expect(pathLooks([row('j', 'unoq', { stale: true, moving: true })])[0]).toMatchObject({ show: false, moving: false })
    expect(pathLooks([row('j', 'unoq', { stale: true }), row('j', 'pi5')])[0]).toMatchObject({ show: true, rx: 'pi5' })
    expect(pathLooks([row('k', 'unoq', { xy_m: null })])[0].show).toBe(false)
  })

  it('use the spot placed in align mode until the brain sends one', () => {
    const placed = structuredClone(DESK_LAYOUT)
    placed.hall.beacons[1].xyz_m = [-14, 6, 1]
    expect(applyLayout(placed)).toBe(true)
    expect(pathLooks([row('j', 'unoq', { xy_m: null })])[0]).toMatchObject({ show: true, xy: [-14, 6] })
  })
})
