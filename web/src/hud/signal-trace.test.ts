import { beforeAll, expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import type { LinkState, StateMsg } from '../room/contract'
import { applyLayout } from '../room/frame'
import { mockState } from '../room/mock'
import { DELAY_MS, SignalHistory, formatDrop, sideDrop, signalSides, traceRuns, traceStatus, type Sample } from './signal-trace'

beforeAll(() => { expect(applyLayout(desk)).toBe(true) })

const link = (id: string, drop_db: number | null, status = 'ok'): LinkState => ({ id, dbm: -60, base_dbm: drop_db === null ? null : -55, drop_db, rate_hz: 9, expected_hz: 9.5, status, why: 0 })

test('the desk layout gives one side per zone, from the links that cross its floor', () => {
  const sides = signalSides()
  expect(sides.map((side) => side.name)).toEqual(['Left', 'Right'])
  expect(sides[0].links.sort()).toEqual(['west>pi5:ble', 'west>pi5b:ble', 'west>unoq:ble'])
  expect(sides[1].links.sort()).toEqual(['east>pi5:ble', 'east>pi5b:ble', 'east>unoq:ble'])
})

test('only Bluetooth lines join a side, also when a Wi-Fi link crosses the floor', () => {
  // The same desk with one more link: the west beacon's place to the board, as Wi-Fi.
  const withWifi = { ...desk, links: [...desk.links, { id: 'west>unoq:wifi', tx: 'west', rx: 'unoq', kind: 'wifi', expected_hz: null }] }
  expect(applyLayout(withWifi)).toBe(true)
  const links = signalSides().flatMap((side) => side.links)
  expect(links).toContain('west>unoq:ble')
  expect(links.filter((id) => !id.endsWith(':ble'))).toEqual([])
  expect(applyLayout(desk)).toBe(true)
})

test('a side reads its deepest fresh link, and nothing when none is fresh', () => {
  const [left] = signalSides()
  expect(sideDrop(left, [link('west>unoq:ble', 2.5), link('west>pi5:ble', 6.1), link('east>unoq:ble', 9)])).toBe(6.1)
  expect(sideDrop(left, [link('west>unoq:ble', 2.5), link('west>pi5:ble', 6.1, 'stale')])).toBe(2.5)
  expect(sideDrop(left, [link('west>unoq:ble', 2.5, 'blind'), link('west>pi5:ble', null)])).toBeNull()
  expect(sideDrop(left, [])).toBeNull()
})

test('says why there is no trace', () => {
  const sides = signalSides()
  const state = mockState('empty', 1, 0)
  expect(traceStatus(state, false, sides)).toBe('ok')
  expect(traceStatus(state, true, sides)).toBe('no-data')
  expect(traceStatus(null, false, sides)).toBe('no-data')
  expect(traceStatus({ ...state, links: [] }, false, sides)).toBe('no-readings')
  expect(traceStatus({ ...state, links: state.links.map((l) => ({ ...l, base_dbm: null, drop_db: null })) }, false, sides)).toBe('no-baseline')
})

test('one sample per message, coloured by the side the person is on', () => {
  const history = new SignalHistory()
  history.refreshSides()
  const state: StateMsg = { ...mockState('still', 7, 2000), t: 1000 }
  history.push(state, 100)
  history.push({ ...state }, 110)
  expect(history.samples).toHaveLength(1)
  expect(history.samples[0].present).toEqual([false, true])
  history.push({ ...state, seq: 8, pred: null }, 200)
  expect(history.samples[1].present).toEqual([false, false])
})

test('readings are joined as they came: a missing one and a pause both break the line', () => {
  const at = (t: number, drop: number | null): Sample => ({ t, drop: [drop], present: [false] })
  const samples = [at(0, 1), at(100, 2), at(200, null), at(300, 3), at(400, 4), at(1000, 5), at(1100, 6)]
  const runs = traceRuns(samples, 0, 1100 + DELAY_MS)
  expect(runs.map((run) => run.map((p) => p.drop))).toEqual([[1, 2], [3, 4], [5, 6]])
  expect(runs[2].at(-1)!.age).toBe(0)
})

test('the newest end is drawn part-way along the line between two real readings, never past them', () => {
  const samples: Sample[] = [{ t: 0, drop: [2], present: [false] }, { t: 100, drop: [4], present: [true] }]
  const [run] = traceRuns(samples, 0, 50 + DELAY_MS)
  expect(run).toEqual([{ age: 50, drop: 2, present: false }, { age: 0, drop: 3, present: true }])
  expect(traceRuns(samples, 0, DELAY_MS - 1)).toEqual([])
})

test('a drop reads as a change from the baseline', () => {
  expect(formatDrop(6.84)).toBe('−6.8 dB')
  expect(formatDrop(-1.2)).toBe('+1.2 dB')
  expect(formatDrop(0.04)).toBe('0.0 dB')
})
