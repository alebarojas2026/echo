import { describe, expect, it } from 'vitest'
import { beamLook, nodePair, overFloor } from './beams'
import type { LinkState } from './contract'

const link = (drop: number | null, status = 'ok'): LinkState => ({
  id: 'east>pi5:ble', dbm: -60, base_dbm: -58, drop_db: drop, rate_hz: 9, expected_hz: 9.5, status, why: 0,
})
const none = new Set<string>()

describe('beam look', () => {
  it('dims as drop_db rises but never disappears', () => {
    const a = beamLook(link(0), false, none).opacity
    const b = beamLook(link(5), false, none).opacity
    const c = beamLook(link(40), false, none).opacity
    expect(a).toBe(1)
    expect(b).toBeLessThan(a)
    expect(c).toBeLessThan(b)
    expect(c).toBeGreaterThan(0.2)
    expect(beamLook(link(-3), false, none).opacity).toBe(1) // a stronger signal never brightens past full
  })

  it('highlights links in pred.why and keeps them readable', () => {
    const look = beamLook(link(12), true, none)
    expect(look.why).toBe(true)
    expect(look.width).toBeGreaterThan(beamLook(link(12), false, none).width)
    expect(look.opacity).toBeGreaterThanOrEqual(0.8)
  })

  it('draws a link that never crosses the floor faint at rest, and in full once it explains the prediction', () => {
    expect(beamLook(link(0), false, none, false).opacity).toBeCloseTo(0.3)
    expect(beamLook(link(0), true, none, false).opacity).toBeGreaterThanOrEqual(0.8)
    expect(beamLook(link(2, 'blind'), false, none, false).opacity).toBe(0.6) // broken reads the same everywhere
  })

  it('draws blind and missing links broken, never empty', () => {
    for (const look of [beamLook(link(2, 'blind'), true, none), beamLook(link(2), false, new Set(['east>pi5:ble'])), beamLook(undefined, false, none)]) {
      expect(look.broken).toBe(true)
      expect(look.why).toBe(false)
      expect(look.opacity).toBeGreaterThan(0.4)
    }
    expect(beamLook(undefined, false, none).status).toBe('missing')
  })
})

describe('node pairs', () => {
  it('gives twin links one key, so they share one "no signal" label', () => {
    expect(nodePair('pi5>unoq:wifi')).toBe(nodePair('pi5>unoq:ble'))
    expect(nodePair('east>pi5:ble')).not.toBe(nodePair('east>unoq:ble'))
    expect(new Set(['pi5>unoq:wifi', 'pi5>unoq:ble', 'east>unoq:ble', 'west>unoq:ble', 'east>pi5:ble', 'west>pi5:ble'].map(nodePair)).size).toBe(5)
  })
})
