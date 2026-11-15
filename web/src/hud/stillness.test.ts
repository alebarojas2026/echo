import { expect, test } from 'vitest'
import { mockState } from './mock-layout'
import { stillness } from './judge-stillness-panel'
test('counts, alerts, acknowledges a wave, and expires it', () => {
  expect(stillness(mockState('still', 0, 7200), false).progress).toBe(.7)
  expect(stillness(mockState('still', 0, 11000), false).text).toMatch(/^No movement /)
  const state = mockState('checkin', 0, 7000)
  expect(stillness(state, false).text).toBe('Wave seen')
  state.t += 7000
  expect(stillness(state, false).text).toBe('')
  expect(stillness(state, true).text).toBe('')
})
