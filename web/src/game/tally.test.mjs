// Run with: node --test web/src/game/
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { addRound, emptyTally, isState, judge, load, resultText, save, STORE_KEY, tallyText, truthCmd, undo, wsUrl } from './tally.js'

const state = (pred, extra = {}) => ({ v: 2, type: 'state', src: 'live', health: { status: 'ok' }, pred, ...extra })
const person = (zone) => ({ present: true, kind: 'person', zone, zone_set: [zone], motion: 'still' })
const memory = () => {
  const m = new Map()
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) }
}

test('found when the radio has the person in the right zone', () => {
  assert.deepEqual(judge(state(person(2)), 100, 2), { outcome: 'found', counted: true, guess: 2, truth: 2 })
})

test('hidden when the radio has the wrong zone, sees nobody, or sees an object', () => {
  assert.equal(judge(state(person(3)), 100, 2).outcome, 'hidden')
  assert.deepEqual(judge(state({ present: false, kind: 'none', zone: 0 }), 100, 4), { outcome: 'hidden', counted: true, guess: 0, truth: 4 })
  assert.equal(judge(state({ present: true, kind: 'object', zone: 4 }), 100, 4).outcome, 'hidden')
})

test('no data when there is no state or it is older than 1 s', () => {
  assert.equal(judge(null, 0, 1).outcome, 'no_data')
  assert.equal(judge(state(person(1)), 1001, 1).outcome, 'no_data')
  assert.equal(judge(state(person(1)), 1000, 1).outcome, 'found')
})

test('not ready when pred is null, and it says so when the sensor is blind', () => {
  assert.deepEqual(judge(state(null), 10, 1), { outcome: 'not_ready', counted: false, guess: null, blind: false })
  assert.equal(judge(state(null, { health: { status: 'blind' } }), 10, 1).blind, true)
})

test('sim and replay rounds are practice: judged but never counted', () => {
  for (const src of ['sim', 'replay']) {
    const result = judge(state(person(1), { src }), 10, 1)
    assert.equal(result.outcome, 'found')
    assert.equal(result.counted, false)
    assert.deepEqual(addRound(emptyTally(), result), emptyTally())
    assert.match(resultText(result), /Practice round, not counted/)
  }
})

test('tally counts live rounds, and undo takes the last one back', () => {
  let t = emptyTally()
  for (const [pred, truth] of [[person(1), 1], [person(2), 3], [person(4), 4], [null, 2]]) {
    t = addRound(t, judge(state(pred), 10, truth))
  }
  assert.deepEqual(t, { found: 2, hidden: 1, rounds: ['found', 'hidden', 'found'] })
  assert.equal(tallyText(t), 'Wi-Fi found 2 of 3. 1 hid.')
  assert.deepEqual(undo(t), { found: 1, hidden: 1, rounds: ['found', 'hidden'] })
  assert.deepEqual(undo(undo(undo(undo(t)))), emptyTally())
  assert.equal(tallyText(emptyTally()), 'No rounds yet')
})

test('tally survives a reload and ignores broken storage', () => {
  const store = memory()
  const t = { found: 1, hidden: 1, rounds: ['hidden', 'found'] }
  save(store, t)
  assert.deepEqual(load(store), t)
  store.setItem(STORE_KEY, '{"found":99,"hidden":0,"rounds":["found"]}')
  assert.deepEqual(load(store), { found: 1, hidden: 0, rounds: ['found'] }) // counts come from the rounds
  store.setItem(STORE_KEY, 'not json')
  assert.deepEqual(load(store), emptyTally())
  assert.deepEqual(load({ getItem() { throw new Error('blocked') } }), emptyTally())
})

test('result sentences name the zones', () => {
  assert.equal(resultText(judge(state(person(2)), 10, 2)), 'Found you in the Chair zone.')
  assert.equal(resultText(judge(state(person(3)), 10, 1)), 'You hid! Wi-Fi looked in the Hall zone, you were in the Bed zone.')
  assert.equal(resultText(judge(state({ present: false, kind: 'none', zone: 0 }), 10, 4)), 'You hid! Wi-Fi saw nobody, you were in the Bathroom zone.')
  assert.match(resultText(judge(null, 0, 1)), /No data/)
  assert.match(resultText(judge(state(null, { health: { status: 'blind' } }), 0, 1)), /blind/)
})

test('truth command and socket address follow the contract', () => {
  assert.deepEqual(truthCmd(3), { v: 2, type: 'cmd', cmd: 'truth', args: { zone: 3 } })
  assert.equal(wsUrl({ hostname: '192.168.77.2', search: '' }), 'ws://192.168.77.2:8765/ws')
  assert.equal(wsUrl({ hostname: 'x', search: '?ws=ws://127.0.0.1:9000/ws' }), 'ws://127.0.0.1:9000/ws')
})

test('only a v2 state message is read', () => {
  assert.equal(isState(state(person(1))), true)
  assert.equal(isState({ ...state(person(1)), v: 1 }), false)
  assert.equal(isState({ ...state(person(1)), v: undefined }), false)
  assert.equal(isState({ v: 2, type: 'event' }), false)
  assert.equal(isState(null), false)
  assert.equal(isState('state'), false)
})
