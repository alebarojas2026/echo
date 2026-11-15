import { beforeAll, expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import { applyLayout } from '../room/frame'
import { mockState } from '../room/mock'
import { tamperWords } from './judge-tamper-panel'

beforeAll(() => { expect(applyLayout(desk)).toBe(true) })

test('names silent devices in plain words, from the layout', () => {
  const state = { ...mockState('blind', 1, 0), armed: true }
  expect(tamperWords(state, false)).toBe('')
  expect(tamperWords({ ...state, tamper: [] }, false)).toBe('')
  expect(tamperWords({ ...state, tamper: ['east'] }, false)).toBe('East beacon unplugged while armed')
  expect(tamperWords({ ...state, tamper: ['east', 'pi5b'] }, false)).toBe('East beacon and Pi B unplugged while armed')
  expect(tamperWords({ ...state, tamper: ['east', 'pi5b', 'h'] }, false)).toBe('East beacon, Pi B and Hall beacon H unplugged while armed')
  expect(tamperWords({ ...state, tamper: ['x9'] }, false)).toBe('A device unplugged while armed')
  expect(tamperWords({ ...state, tamper: ['east'] }, true)).toBe('')
})
