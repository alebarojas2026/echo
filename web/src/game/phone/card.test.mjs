// Run with: node --test web/src/game/phone/card.test.mjs
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { card, checkinText, isState, MOCKS, shouldChime, wsUrl } from './card.js'

const show = (name, age = 100) => card(MOCKS[name], age)

test('calm: says who is where, with the zone name', () => {
  const c = show('calm')
  assert.deepEqual([c.mode, c.label, c.title, c.detail, c.zone], ['calm', 'ALL GOOD', 'Someone is in the Chair zone.', 'Moving.', 'Chair'])
  assert.equal(show('empty').title, 'Nobody is in the room.')
})

test('counting: still calm, and the seconds come from the state', () => {
  const c = show('counting')
  assert.deepEqual([c.mode, c.title, c.detail], ['calm', 'Someone is in the Bathroom zone.', 'No movement for 7 s.'])
})

test('alert: no-movement wording with the zone and the limit from the state', () => {
  const c = show('alert')
  assert.deepEqual([c.mode, c.label, c.title], ['alert', 'NO-MOVEMENT ALERT', 'No movement in the Bathroom for 10 s.'])
  const noLimit = card({ ...MOCKS.alert, alert: { state: 'check_on', zone: null, still_s: 12, limit_s: null } }, 0)
  assert.equal(noLimit.title, 'No movement in the room.')
})

test('check-in: back to calm, with the time of the last check-in', () => {
  const c = show('checkin')
  assert.equal(c.mode, 'calm')
  assert.equal(c.checkinT, 1763149511000)
  assert.equal(checkinText(c.checkinT, (t) => `at ${t}`), 'Last check-in at 1763149511000')
  assert.equal(checkinText(null), 'No check-in yet')
  assert.match(checkinText(1763149511000), /^Last check-in \d/)
})

test('the whole story: calm, counting, alert, check-in', () => {
  const modes = ['calm', 'counting', 'alert', 'alert', 'checkin'].map((name) => show(name).mode)
  assert.deepEqual(modes, ['calm', 'calm', 'alert', 'alert', 'calm'])
  const chimes = modes.map((mode, i) => shouldChime(modes[i - 1], mode))
  assert.deepEqual(chimes, [false, false, true, false, false]) // once, when the alert starts
  assert.equal(shouldChime(undefined, 'alert'), true) // the page opened during an alert
})

test('no data and sensor blind are never shown as an empty room', () => {
  assert.equal(card(null, 0).mode, 'nodata')
  assert.equal(show('alert', 1001).mode, 'nodata')
  assert.equal(show('alert', 1000).mode, 'alert')
  assert.equal(card({ ...MOCKS.calm, v: 1 }, 0).mode, 'nodata')
  const blind = show('blind')
  assert.deepEqual([blind.mode, blind.label], ['blind', 'SENSOR BLIND'])
  assert.match(blind.detail, /does not mean the room is empty/)
  assert.equal(card({ ...MOCKS.calm, pred: null }, 0).mode, 'waiting')
})

test('a blind sensor outranks an alert that was showing', () => {
  assert.equal(card({ ...MOCKS.alert, health: { status: 'blind', blind: [], reason: 'rate' } }, 0).mode, 'blind')
})

test('every card has a word for its colour and only numbers from the state', () => {
  for (const [name, state] of Object.entries(MOCKS)) {
    const c = card(state, 0)
    assert.ok(c.label.length > 0, name)
    const allowed = new Set([String(state.alert.limit_s), String(Math.floor(state.alert.still_s))])
    for (const n of `${c.title} ${c.detail}`.match(/\d+/g) ?? []) assert.ok(allowed.has(n), `${name}: ${n}`)
  }
})

test('message check and socket address follow the contract', () => {
  assert.equal(isState(MOCKS.calm), true)
  assert.equal(isState({ v: 2, type: 'event' }), false)
  assert.equal(wsUrl({ hostname: '192.168.77.2', search: '' }), 'ws://192.168.77.2:8765/ws')
  assert.equal(wsUrl({ hostname: 'x', search: '?ws=ws://127.0.0.1:9000/ws' }), 'ws://127.0.0.1:9000/ws')
})

test('right after a check-in the card does not say 0 s', () => {
  assert.equal(show('checkin').detail, 'Standing still.')
})
