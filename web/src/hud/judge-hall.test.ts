import { expect, test, vi } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import gate from '../../tests/fixtures/gate-layout.json'
import type { StateMsg } from '../room/contract'
import { CHECKIN_WORDS, WALKED, WALKED_MS, hallFirst, hallMoment, walkedThrough } from './judge-hall'
import type { HudLayout } from './layout'
import { alignMockState, mockState } from './mock-layout'

// The hall-first page: every state the one spot can be in is one headline and one line under it.
const layout: HudLayout = gate
const base = (scenario: 'still' | 'empty' | 'blind', over: Partial<StateMsg> = {}): StateMsg => ({ ...alignMockState(mockState(scenario, 1, 7000), layout)!, ...over })
const here = (motion: 'moving' | 'still', over: Partial<StateMsg> = {}): StateMsg => {
  const state = base('still', over)
  return { ...state, pred: { ...state.pred!, motion } }
}
const quiet = { state: 'none', zone: null, still_s: 0, limit_s: 10 } as StateMsg['alert']

test('the page is for the one-spot layout only', () => {
  expect(hallFirst(layout)).toBe(true)
  expect(hallFirst(desk as HudLayout)).toBe(false)
})

test('nobody, somebody still and somebody moving', () => {
  expect(hallMoment(base('empty'), false, layout)).toEqual({ headline: 'Nobody is here.', detail: 'Step up to the desk.', tone: '' })
  expect(hallMoment(here('still', { alert: { state: 'counting', zone: 1, still_s: 9.6, limit_s: 10 } }), false, layout)).toEqual({ headline: 'Someone is here.', detail: 'Standing still for 9 s', tone: '' })
  expect(hallMoment(here('still', { alert: quiet }), false, layout).detail).toBe('Standing still')
  expect(hallMoment(here('moving', { alert: { state: 'counting', zone: 1, still_s: 2, limit_s: 10 } }), false, layout)).toEqual({ headline: 'Someone is here.', detail: 'Moving', tone: '' })
})

test('the no-movement alert is the fault colour with its words, and a check-in answers it', () => {
  const alert = hallMoment(here('moving', { alert: { state: 'check_on', zone: 1, still_s: 13.4, limit_s: 10 } }), false, layout)
  expect(alert).toEqual({ headline: 'No movement for 13 s', detail: CHECKIN_WORDS, tone: 'fault' })
  expect(CHECKIN_WORDS).toBe("Step aside and back to say you're okay.")
  const state = here('moving', { alert: quiet })
  expect(hallMoment({ ...state, checkin: { t: state.t - 1000, link: 'pi5>pi5b:wifi' } }, false, layout)).toEqual({ headline: 'Check-in received', detail: 'Someone is here, moving', tone: 'action' })
  expect(hallMoment({ ...state, checkin: { t: state.t - 7000, link: 'pi5>pi5b:wifi' } }, false, layout).headline).toBe('Someone is here.')
})

test('an alert is never shown on a spot the board calls empty', () => {
  const empty = base('empty', { alert: { state: 'check_on', zone: 1, still_s: 13, limit_s: 10 } })
  expect(hallMoment(empty, false, layout).headline).toBe('Nobody is here.')
})

test('armed, blind, no data, getting ready and a replayed second keep the words they had', () => {
  expect(hallMoment(here('still', { armed: true, alert: quiet }), false, layout)).toMatchObject({ headline: 'Someone is here.', tone: 'fault' })
  expect(hallMoment(base('empty', { armed: true, tamper: ['pi5b'] }), false, layout)).toEqual({ headline: 'Pi B unplugged while armed', detail: '', tone: 'fault' })
  const blind = hallMoment(base('blind'), false, layout)
  expect([blind.headline, blind.tone]).toEqual(['Sensor blind', ''])
  expect(blind.detail).toMatch(/\nAlerts are paused$/)
  expect(hallMoment(base('still'), true, layout)).toEqual({ headline: 'No data', detail: 'Last update more than 1 s ago', tone: '' })
  expect(hallMoment(null, false, layout).headline).toBe('No data')
  expect(hallMoment(base('empty', { pred: null, links: [], model: { trained: false } as StateMsg['model'] }), false, layout).headline).toBe('Getting ready')
  expect(hallMoment({ ...here('still'), replay: { kind: 'none' } } as StateMsg, false, layout).tone).toBe('')
  expect(hallMoment({ ...here('moving', { alert: quiet }), replay: { kind: 'record' } } as StateMsg, false, layout)).toEqual({ headline: 'Someone is here.', detail: 'Moving', tone: '' })
})

test('a walk through is said only while nobody is here and the space is not armed', () => {
  expect(WALKED).toEqual({ headline: 'Someone walked through.', detail: 'Nobody stopped.', tone: '' })
  expect(`${WALKED.headline} ${WALKED.detail}`).not.toMatch(/left|right|side|\d/i)
  expect(hallMoment(base('empty'), false, layout, true)).toEqual(WALKED)
  // Not asked for: exactly what the page said before.
  expect(hallMoment(base('empty'), false, layout, false)).toEqual(hallMoment(base('empty'), false, layout))
  // A person, an alert, an armed space, a blind sensor and no data all come first.
  const still = here('still', { alert: quiet })
  expect(hallMoment(still, false, layout, true)).toEqual(hallMoment(still, false, layout))
  const alert = here('still', { alert: { state: 'check_on', zone: 1, still_s: 13.4, limit_s: 10 } })
  expect(hallMoment(alert, false, layout, true).tone).toBe('fault')
  for (const state of [base('empty', { armed: true }), base('blind'), base('empty', { armed: true, tamper: ['pi5b'] })]) {
    expect(hallMoment(state, false, layout, true)).toEqual(hallMoment(state, false, layout))
    expect(hallMoment(state, false, layout, true).headline).not.toBe(WALKED.headline)
  }
  expect(hallMoment(base('empty'), true, layout, true).headline).toBe('No data')
  expect(hallMoment(null, false, layout, true).headline).toBe('No data')
})

test('the walk-through lasts about 3 s from the passed_by event, on the one spot only, and a reset ends it', () => {
  vi.useFakeTimers()
  try {
    let fire: (event: { kind: string }) => void = () => {}
    let off = 0
    const feed = { onEvent(fn: (event: { kind: string }) => void) { fire = fn; return () => { off++ } } }
    let clock = 1000
    let changes = 0
    const walked = walkedThrough(feed, () => { changes++ }, () => clock, () => true)
    expect(walked.active()).toBe(false)
    for (const kind of ['enter', 'intrusion', 'disarmed', 'reset']) fire({ kind })
    expect([walked.active(), changes]).toEqual([false, 0]) // a board that never sends it changes nothing
    fire({ kind: 'passed_by' })
    expect([walked.active(), changes]).toEqual([true, 1])
    clock += WALKED_MS - 1
    expect(walked.active()).toBe(true)
    clock += 2
    expect(walked.active()).toBe(false)
    vi.advanceTimersByTime(WALKED_MS + 50)
    expect(changes).toBe(2) // the page is told when it ends, so the words go without waiting for a state
    fire({ kind: 'passed_by' })
    fire({ kind: 'reset' })
    expect([walked.active(), changes]).toEqual([false, 4])
    walked.dispose()
    expect(off).toBe(1)
    // Any other layout: the event is not a walk through the one spot.
    const other = walkedThrough(feed, () => { changes++ }, () => clock, () => false)
    fire({ kind: 'passed_by' })
    expect([other.active(), changes]).toEqual([false, 4])
    expect(WALKED_MS).toBe(3000)
  } finally {
    vi.useRealTimers()
  }
})

test('an arrival and a leaving within 1.5 s is a walk through too; a longer visit and a dropped reading are not', () => {
  vi.useFakeTimers()
  try {
    const feed = { onEvent: () => () => {} }
    let clock = 0
    let changes = 0
    const walked = walkedThrough(feed, () => { changes++ }, () => clock, () => true)
    const at = (ms: number, here: boolean | null) => { clock = ms; walked.seen(here) }
    // A slow crossing: the board says enter, then exit 0.8 s later.
    at(0, false); at(1000, true); at(1400, true)
    expect(walked.active()).toBe(false) // while they are in the line it is "Someone is here."
    at(1800, false)
    expect(walked.active()).toBe(true)
    at(1900, false)
    clock = 1800 + 2999
    expect(walked.active()).toBe(true)
    clock = 1800 + 3001
    expect(walked.active()).toBe(false)
    vi.advanceTimersByTime(3100)
    expect(changes).toBe(1) // told when the words are due to go
    // A stand of ten seconds, then leaving: never a walk through.
    at(10_000, true); for (let t = 10_100; t <= 20_000; t += 100) at(t, true)
    at(20_100, false)
    expect(walked.active()).toBe(false)
    // A visit of just over the limit is a visit.
    at(30_000, true); at(31_600, false)
    expect(walked.active()).toBe(false)
    // One dropped reading at the start of a stand: they had not left, and nothing is said about a walk.
    at(40_000, true); at(40_500, false)
    expect(walked.active()).toBe(true)
    at(40_700, true)
    expect(walked.active()).toBe(false)
    at(45_000, false) // the stand then lasted five seconds
    expect(walked.active()).toBe(false)
    // Nothing to go by (no data, blind, armed, a replay) starts the count again: no walk is made up from it.
    at(50_000, true); at(50_300, null); at(50_600, false)
    expect(walked.active()).toBe(false)
    // Another layout: never.
    const other = walkedThrough(feed, () => {}, () => clock, () => false)
    clock = 60_000; other.seen(true); clock = 60_500; other.seen(false)
    expect(other.active()).toBe(false)
    walked.dispose()
  } finally {
    vi.useRealTimers()
  }
})
