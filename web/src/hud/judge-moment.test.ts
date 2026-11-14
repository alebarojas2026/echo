import { expect, test } from 'vitest'
import { mockState } from '../room/mock'
import { judgeMoment } from './judge-moment'
test('headlines distinguish person, object, empty, stale and blind', () => {
  expect(judgeMoment(mockState('still', 0, 7000), false)[0]).toBe('Still in the bathroom')
  expect(judgeMoment(mockState('object', 0, 1000), false)[0]).toBe('An object, not a person')
  expect(judgeMoment(mockState('empty', 0, 1000), false)[0]).toBe('Nobody is here')
  expect(judgeMoment(mockState('blind', 0, 1000), false)[0]).toBe('Sensor blind')
  expect(judgeMoment(null, true)[0]).toBe('No data')
})
