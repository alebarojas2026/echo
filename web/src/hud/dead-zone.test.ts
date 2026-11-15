import { afterEach, expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import file from '../../../radio/nodes.json'
import { applyLayout } from '../room/frame'
import { mockState } from './mock-layout'
import { deadZone, holdAdvice, moveWords, wifiLine } from './dead-zone'
import { judgeMoment } from './judge-moment'

afterEach(() => { applyLayout(file) })

test('the Wi-Fi line reads the router link as the board sent it, and never a number it does not have', () => {
  applyLayout(desk)
  const state = mockState('empty', 0, 1000)
  const wifi = state.links.find(link => link.id === 'pi5>unoq:wifi')!
  wifi.drop_db = 0.3
  expect(wifiLine(state, false)).toEqual({ status: 'strong', word: 'strong', value: '−0.3 dB', ends: 'Pi A to Board' })
  wifi.drop_db = 2.9
  expect(wifiLine(state, false).word).toBe('strong')
  wifi.drop_db = 3
  expect(wifiLine(state, false)).toMatchObject({ status: 'weak', word: 'weak', value: '−3.0 dB' })
  wifi.drop_db = -1.2
  expect(wifiLine(state, false)).toMatchObject({ word: 'strong', value: '+1.2 dB' })
  wifi.drop_db = null
  expect(wifiLine(state, false)).toMatchObject({ status: 'no-baseline', word: 'no baseline yet' })
  wifi.status = 'stale'
  expect(wifiLine(state, false)).toMatchObject({ status: 'no-signal', value: '' })
  state.links = []
  expect(wifiLine(state, false)).toMatchObject({ status: 'no-signal', value: '' })
  expect(wifiLine(state, true)).toMatchObject({ status: 'no-data', value: '' })
  expect(wifiLine(null, true).status).toBe('no-data')
})

test('the move is read from the advice: left and right on the desk, compass points on the square', () => {
  applyLayout(desk)
  expect(moveWords({ move_m: [-0.3, 0] })).toBe('30 cm left')
  expect(moveWords({ move_m: [0.25, 0] })).toBe('25 cm right')
  expect(moveWords({ move_m: [0, 0] })).toBe('')
  // A layout with no strip (the 2 x 2 m square was one) has compass points.
  expect(moveWords({ move_m: [-0.3, 0] }, false)).toBe('30 cm west')
  expect(moveWords({ move_m: [0, 0.3] }, false)).toBe('30 cm north')
})

test('found, measuring, and the gain or loss the board measured', () => {
  applyLayout(desk)
  expect(deadZone(mockState('empty', 0, 1000), false)).toBeNull()
  const state = mockState('object', 0, 1000)
  expect(deadZone(state, true)).toBeNull()
  state.advice!.before_dbm = -71.2
  expect(deadZone(state, false)).toMatchObject({ step: 'found', headline: 'Dead zone found', detail: 'Something is blocking the Wi-Fi from Pi A to Board', text: 'Move the router 30 cm left', way: -1, before: -71.2, after: null })
  expect(judgeMoment(state, false, desk)).toEqual(['Dead zone found', 'Something is blocking the Wi-Fi from Pi A to Board'])
  state.router = state.advice!.to_spot
  state.pred = null
  expect(deadZone(state, false)).toMatchObject({ step: 'measuring', headline: 'Router moved', text: 'Measuring…' })
  state.advice!.after_dbm = -63.4
  expect(deadZone(state, false)).toMatchObject({ step: 'better', headline: 'Dead zone fixed', detail: 'Router moved 30 cm left', text: '+7.8 dB stronger', after: -63.4 })
  expect(judgeMoment(state, false, desk)[0]).toBe('Dead zone fixed')
  state.advice!.after_dbm = -73.3
  expect(deadZone(state, false)).toMatchObject({ step: 'worse', headline: 'No gain at this spot', text: '−2.1 dB weaker' })
  state.advice!.after_dbm = -71.2
  expect(deadZone(state, false)).toMatchObject({ step: 'worse', text: 'No change' })
})

test('advice with no move in it falls back to the board\'s own sentence', () => {
  const state = mockState('object', 0, 1000)
  state.advice!.move_m = [0, 0]
  expect(deadZone(state, false)!.text).toBe(state.advice!.text)
})

test('the last advice is kept only while the router stays on the advised spot', () => {
  const advised = mockState('object', 0, 1000)
  expect(holdAdvice(advised)).toBe(advised)
  const moved = { ...mockState('empty', 1, 1100), router: advised.advice!.to_spot }
  expect(holdAdvice(moved).advice).toBe(advised.advice)
  const elsewhere = { ...moved, router: 'S-E30' }
  expect(holdAdvice(elsewhere).advice).toBeNull()
  expect(holdAdvice(moved).advice).toBeNull()
  holdAdvice(advised)
  expect(holdAdvice(mockState('empty', 2, 1200)).advice).toBeNull()
  expect(holdAdvice(null)).toBeNull()
})
