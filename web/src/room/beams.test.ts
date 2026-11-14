import { describe, expect, it } from 'vitest'
import { beamLook } from './beams'
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

  it('draws blind and missing links broken, never empty', () => {
    for (const look of [beamLook(link(2, 'blind'), true, none), beamLook(link(2), false, new Set(['east>pi5:ble'])), beamLook(undefined, false, none)]) {
      expect(look.broken).toBe(true)
      expect(look.why).toBe(false)
      expect(look.opacity).toBeGreaterThan(0.4)
    }
    expect(beamLook(undefined, false, none).status).toBe('missing')
  })
})
