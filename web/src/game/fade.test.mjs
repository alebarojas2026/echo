// Run with: node --test web/src/game/
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { quietChange } from './fade.js'

test('only a real text change fades; a ticking count swaps in place', () => {
  assert.equal(quietChange(undefined, 'Ready'), true)              // first paint
  assert.equal(quietChange('Still for 4 s', 'Still for 5 s'), true)
  assert.equal(quietChange('No data', 'Ready'), false)
  assert.equal(quietChange('__', '3'), false)                      // the first real round is a change
})
