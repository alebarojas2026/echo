import { expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import gate from '../../tests/fixtures/gate-layout.json'
import type { LinkState, StateMsg } from '../room/contract'
import { judgeMoment } from './judge-moment'
import { tamperWords } from './judge-tamper-panel'
import { linkName, zoneIn, zoneName, zonePlace, type HudLayout } from './layout'
import { alignMockState, mockState } from './mock-layout'
import { SignalHistory, sideDrop, signalSides, traceStatus } from './signal-trace'

// The gate layout: three devices, six links, one spot ("At the desk"). Nothing on the hud may name a side.
const layout: HudLayout = gate
const SIDE = /\b(left|right|side|east|west)\b/i
const link = (id: string, drop_db: number | null, status = 'ok'): LinkState => ({ id, dbm: -60, base_dbm: -55, drop_db, rate_hz: 6, expected_hz: 6, status, why: 0 })
const here = (motion: 'moving' | 'still'): StateMsg => {
  const state = alignMockState(mockState('still', 1, 7000), layout)!
  return { ...state, pred: { ...state.pred!, motion } }
}

test('the mock follows a one-zone layout: zone 1, zone_set [1], probs [empty, the spot]', () => {
  const pred = here('still').pred!
  expect([pred.zone, pred.zone_set, pred.probs]).toEqual([1, [1], [0, 1]])
  expect(alignMockState(mockState('empty', 1, 0), layout)!.pred!.probs).toEqual([1, 0])
})

test('headlines say where by the zone name, and never a side', () => {
  expect(judgeMoment(here('still'), false, layout)).toEqual(['Still at the desk', ''])
  expect(judgeMoment(here('moving'), false, layout)).toEqual(['Moving at the desk', ''])
  expect(judgeMoment(alignMockState(mockState('empty', 1, 0), layout), false, layout)[0]).toBe('Nobody is here')
  expect(zoneName(1, layout)).toBe('At the desk')
  expect(zonePlace(1, layout)).toBe('at the desk')
  expect(zonePlace(1, { ...layout, zones: [{ id: 1, name: 'By the door', still_alert_s: 10 }] })).toBe('by the door')
  for (const motion of ['still', 'moving'] as const) expect(judgeMoment(here(motion), false, layout).join(' ')).not.toMatch(SIDE)
  // the camera line: "sees them at the desk", never "in At the desk"
  expect(zoneIn(1, layout)).toBe('at the desk')
  expect(zoneIn(desk.zones[0].id, desk)).toBe('in Left')
  // the two-zone desk still names its sides
  expect(zonePlace(desk.zones[0].id, desk)).toBe('on the left')
})

test('the signal trace is one row for the spot, from the Bluetooth lines that cross it', () => {
  const sides = signalSides(layout)
  expect(sides).toEqual([{ zone: 1, name: 'At the desk', links: ['pi5b>unoq:ble', 'pi5>pi5b:ble', 'pi5b>pi5:ble'] }])
  // the deepest fresh line; the desk lines and the Wi-Fi line never count
  expect(sideDrop(sides[0], [link('pi5>unoq:ble', 30), link('pi5>pi5b:wifi', 25), link('pi5b>unoq:ble', 11.5), link('pi5b>pi5:ble', 13, 'stale')])).toBe(11.5)
  expect(sideDrop(sides[0], [link('pi5>unoq:ble', 30), link('pi5>unoq:wifi', 9)])).toBeNull()
  expect(traceStatus({ ...here('still'), links: [link('pi5b>unoq:ble', 12)] }, false, sides)).toBe('ok')
  expect(traceStatus({ ...here('still'), links: [link('pi5>unoq:wifi', 1)] }, false, sides)).toBe('no-readings')
})

test('the row turns the person colour while someone is on the spot', () => {
  const history = new SignalHistory()
  history.refreshSides(layout)
  const state = { ...here('still'), links: [link('pi5b>unoq:ble', 12), link('pi5>pi5b:ble', 10)] }
  history.push({ ...state, seq: 1 }, 100)
  history.push({ ...state, seq: 2, pred: { ...state.pred!, present: false, kind: 'none', zone: 0, zone_set: [], motion: null } }, 200)
  expect(history.samples.map((s) => [s.drop, s.present])).toEqual([[[12], [true]], [[12], [false]]])
})

test('a spot that no Bluetooth line crosses has no row, and a two-zone layout keeps its sides', () => {
  expect(signalSides({ ...layout, links: layout.links.map((l) => ({ ...l, crosses_spot: false })) })).toEqual([])
  // crosses_spot on a layout with two zones is not a spot: the sides are still worked out from the floor
  const two = { ...desk, links: desk.links.map((l) => ({ ...l, crosses_spot: true })) }
  expect(signalSides(two)).toEqual(signalSides(desk))
})

test('devices and lines are named from the three in the file', () => {
  expect(layout.links.map((l) => linkName(l.id, layout))).toEqual([
    'Pi A to Board, Wi-Fi', 'Pi A to Board, Bluetooth', 'Pi B to Board, Bluetooth', 'Pi A to Pi B, Wi-Fi', 'Pi A to Pi B, Bluetooth', 'Pi B to Pi A, Bluetooth'])
  const armed = { ...here('still'), armed: true, tamper: ['pi5b'] }
  expect(tamperWords(armed, false)).toBe('Pi B unplugged while armed')
  expect(tamperWords({ ...armed, tamper: ['pi5', 'pi5b'] }, false)).toBe('Pi A and Pi B unplugged while armed')
})
