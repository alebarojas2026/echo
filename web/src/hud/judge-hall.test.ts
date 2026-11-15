import { expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import gate from '../../tests/fixtures/gate-layout.json'
import type { StateMsg } from '../room/contract'
import { CHECKIN_WORDS, hallFirst, hallMoment } from './judge-hall'
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
  expect(CHECKIN_WORDS).toBe('Step aside and back to say you\u2019re okay.')
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
})
