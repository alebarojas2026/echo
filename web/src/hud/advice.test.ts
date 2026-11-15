import { vi } from 'vitest'
// This router-move scenario deliberately uses the legacy desk fixture.
vi.mock('../../../radio/nodes.json', async () => ({ default: (await import('../../tests/fixtures/desk-layout.json')).default }))
import { expect, test } from 'vitest'
import { mockState } from './mock-layout'
import { adviceResult } from './judge-advice-panel'
test('hides absent advice and distinguishes measured gain from missing results', () => {
  expect(adviceResult(mockState('empty', 0, 0), false)).toBeNull()
  const state = mockState('object', 0, 1000)
  state.router = state.advice!.to_spot!
  expect(adviceResult(state, false)!.text).toBe('Measuring…')
  state.advice!.before_dbm = -71.2
  state.advice!.after_dbm = -63.4
  expect(adviceResult(state, false)!.text).toBe('+7.8 dB stronger')
  state.advice!.after_dbm = -73.3
  expect(adviceResult(state, false)!.text).toBe('−2.1 dB weaker')
})
