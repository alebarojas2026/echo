import { describe, expect, it } from 'vitest'
import { amberDb, beamLook, DROPPING_DB, explains, nodePair, overFloor, WHY_OFF_MS, WHY_ON_MS } from './beams'
import { Held } from './motion'
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

  it('counts a link as explaining only when it is in pred.why and its own drop is 3 dB or more', () => {
    expect(DROPPING_DB).toBe(3)
    expect(explains(link(3), true)).toBe(true)
    expect(explains(link(9.8), true)).toBe(true)
    expect(explains(link(2.9), true)).toBe(false) // listed, but sitting at its baseline
    expect(explains(link(9.8), false)).toBe(false) // dropping, but not what the brain went by
    expect(explains(link(-4), true)).toBe(false) // a stronger signal is not a drop
    expect(explains(link(null), true)).toBe(false) // no baseline yet
    expect(explains(undefined, true)).toBe(false)
  })

  it('takes the drop that lights a line from the address when it is set, else 3 dB', () => {
    const at = (q: string) => amberDb(new URLSearchParams(q))
    expect(at('')).toBe(3)
    expect(at('amber_db=5')).toBe(5)
    expect(at('amber_db=4.5')).toBe(4.5)
    expect(at('amber_db=0')).toBe(3) // would light every listed line: not believed
    expect(at('amber_db=99')).toBe(3)
    expect(at('amber_db=')).toBe(3)
    expect(at('amber_db=abc')).toBe(3)
    expect(explains(link(4), true, 5)).toBe(false)
    expect(explains(link(5), true, 5)).toBe(true)
  })

  it('holds the highlight steady while a link wobbles across the 3 dB line', () => {
    const held = new Held<boolean>(false, (on) => (on ? WHY_ON_MS : WHY_OFF_MS))
    const at = (drop: number, ms: number) => held.update(explains(link(drop), true), ms)
    // Ten readings a second, in and out of the line every 200 ms: never lit.
    for (let ms = 0; ms < 2200; ms += 100) expect(at(Math.floor(ms / 200) % 2 ? 3.4 : 2.6, ms)).toBe(false)
    // Over the line and staying there: lit after 300 ms, not before.
    expect(at(5, 2200)).toBe(false)
    expect(at(5, 2400)).toBe(false)
    expect(at(5, 2500)).toBe(true)
    // Dips under for 400 ms and comes back: stays lit.
    for (let ms = 2600; ms < 3000; ms += 100) expect(at(2.5, ms)).toBe(true)
    expect(at(5, 3000)).toBe(true)
    // Under for 500 ms: lets go.
    expect(at(1, 3100)).toBe(true)
    expect(at(1, 3500)).toBe(true)
    expect(at(1, 3600)).toBe(false)
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
