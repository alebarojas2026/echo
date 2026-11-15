import { expect, test } from 'vitest'
import { presenceTile } from './proof-visibility'

test('the presence tile says the counts as measured, with the always-empty score beside them', () => {
  expect(presenceTile({ correct: 19, total: 20, always_empty_correct: 10 })).toEqual({ score: '19 of 20', baseline: 'always-empty would score 10 of 20' })
  expect(presenceTile({ correct: 0, total: 20, always_empty_correct: 20 })).toEqual({ score: '0 of 20', baseline: 'always-empty would score 20 of 20' })
  expect(presenceTile({ correct: 19, total: 20, always_empty_correct: null })).toEqual({ score: '19 of 20', baseline: '' })
})

test('nothing measured is never a number', () => {
  for (const value of [undefined, null, { correct: null, total: null, always_empty_correct: null }, { correct: 5, total: null, always_empty_correct: 3 }, { correct: null, total: 20, always_empty_correct: 10 }, { correct: 0, total: 0, always_empty_correct: 0 }]) {
    expect(presenceTile(value)).toEqual({ score: '__', baseline: '' })
  }
})
