import { expect, test, vi } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import gate from '../../tests/fixtures/gate-layout.json'
import type { StateMsg } from '../room/contract'
import { CHECKIN_WORDS, NOBODY, WALKED, WALKED_MS, earlyMoment, hallFirst, hallMoment, walkedThrough } from './judge-hall'
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

test('an enter event and its exit within 1.5 s is a walk through too; only the board\'s events start it', () => {
  vi.useFakeTimers()
  try {
    let fire: (event: { kind: string; t?: number }) => void = () => {}
    const feed = { onEvent(fn: (event: { kind: string; t?: number }) => void) { fire = fn; return () => {} } }
    let changes = 0
    const walked = walkedThrough(feed, () => { changes++ }, () => 0, () => true)
    // A slow crossing: the board records enter, then exit 0.8 s later, by its own clock.
    fire({ kind: 'enter', t: 100_000 })
    expect(walked.active()).toBe(false)
    fire({ kind: 'exit', t: 100_800 })
    expect([walked.active(), changes]).toEqual([true, 1])
    fire({ kind: 'reset' })
    expect([walked.active(), changes]).toEqual([false, 2])
    // A stand of ten seconds, and one of just over the limit: a visit, never a walk through.
    fire({ kind: 'enter', t: 200_000 }); fire({ kind: 'exit', t: 210_000 })
    fire({ kind: 'enter', t: 300_000 }); fire({ kind: 'exit', t: 301_501 })
    expect(walked.active()).toBe(false)
    // Exactly at the limit it still is one.
    fire({ kind: 'enter', t: 400_000 }); fire({ kind: 'exit', t: 401_500 })
    expect(walked.active()).toBe(true)
    fire({ kind: 'reset' })
    // An exit with no enter before it, a second exit, a clock that ran backwards, an event with no time: nothing.
    fire({ kind: 'exit', t: 500_000 })
    fire({ kind: 'enter', t: 600_000 }); fire({ kind: 'exit', t: 600_500 }); fire({ kind: 'reset' }); fire({ kind: 'exit', t: 600_900 })
    fire({ kind: 'enter', t: 700_000 }); fire({ kind: 'exit', t: 699_000 })
    fire({ kind: 'enter' }); fire({ kind: 'exit' })
    // A reset between the two is a new start.
    fire({ kind: 'enter', t: 800_000 }); fire({ kind: 'reset' }); fire({ kind: 'exit', t: 800_400 })
    expect(walked.active()).toBe(false)
    // There is no way to start it from a state: the tracker takes events and nothing else.
    expect(Object.keys(walked).sort()).toEqual(['active', 'dispose'])
    // Another layout: never.
    const other = walkedThrough(feed, () => {}, () => 0, () => false)
    fire({ kind: 'enter', t: 900_000 }); fire({ kind: 'exit', t: 900_500 })
    expect(other.active()).toBe(false)
    walked.dispose()
  } finally {
    vi.useRealTimers()
  }
})

test('"Someone is here." is said at once; the line under it waits 1.5 s, and "for 0 s" is never said', () => {
  const still = (still_s: number) => hallMoment(here('still', { alert: { state: 'counting', zone: 1, still_s, limit_s: 10 } }), false, layout)
  const someone = still(0.4)
  expect(someone).toEqual({ headline: 'Someone is here.', detail: 'Standing still', tone: '' }) // no "for 0 s"
  expect(still(0.99).detail).toBe('Standing still')
  expect(still(1).detail).toBe('Standing still for 1 s') // the board's count, from the true arrival
  expect(still(2.7).detail).toBe('Standing still for 2 s')
  // Inside the window: the headline as it is, nothing under it.
  expect(earlyMoment(someone, 0)).toEqual({ headline: 'Someone is here.', detail: '', tone: '' })
  expect(earlyMoment(still(1.2), 1499)).toEqual({ headline: 'Someone is here.', detail: '', tone: '' })
  const moving = hallMoment(here('moving', { alert: quiet }), false, layout)
  expect(earlyMoment(moving, 700)).toEqual({ headline: 'Someone is here.', detail: '', tone: '' })
  // At 1.5 s the line is said, and from then on.
  expect(earlyMoment(still(1.5), 1500)).toBeNull()
  expect(earlyMoment(someone, 9000)).toBeNull()
  // Nothing else changes: an armed space, an alert, a check-in, nobody, a walk through, no clock to go by.
  const armed = hallMoment(here('still', { armed: true, alert: quiet }), false, layout)
  expect(earlyMoment(armed, 200)).toBeNull()
  const alert = hallMoment(here('still', { alert: { state: 'check_on', zone: 1, still_s: 13.4, limit_s: 10 } }), false, layout)
  expect(earlyMoment(alert, 200)).toBeNull()
  const state = here('moving', { alert: quiet })
  const checkin = hallMoment({ ...state, checkin: { t: state.t - 1000, link: 'pi5>pi5b:wifi' } }, false, layout)
  expect(earlyMoment(checkin, 200)).toBeNull()
  expect(earlyMoment(NOBODY, null)).toBeNull()
  expect(earlyMoment(NOBODY, 200)).toBeNull()
  expect(earlyMoment(WALKED, 200)).toBeNull()
  expect(earlyMoment(someone, null)).toBeNull()
})
