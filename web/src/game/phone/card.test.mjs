// Run with: node --test web/src/game/phone/card.test.mjs
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { card, checkinText, followState, isEvent, isState, MOCK_EVENTS, MOCKS, noEvents, PASSED_BY_MS, shouldChime, takeEvent, tamperText, wsUrl } from './card.js'
import { useDevices, useZones, ZONES } from '../zones.js'

const show = (name, age = 100) => card(MOCKS[name], age, MOCK_EVENTS[name])

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

test('alert: the hint names the check-in the layout has: step aside and back on one spot, a wave elsewhere', () => {
  const before = { ...ZONES }
  assert.equal(show('alert').detail, 'A wave or a tap on reset clears it.')
  useZones({ zones: [{ id: 1, name: 'At the desk' }], presence: { line: 'pi5>pi5b:wifi' } })
  const spot = card({ ...MOCKS.alert, alert: { state: 'check_on', zone: 1, still_s: 12, limit_s: 10 } }, 0)
  assert.equal(spot.detail, 'Stepping aside and back, or a tap on reset, clears it.')
  assert.doesNotMatch(spot.detail, /wave/i)
  useZones({ zones: Object.entries(before).map(([id, name]) => ({ id: Number(id), name })) })
  assert.equal(show('alert').detail, 'A wave or a tap on reset clears it.')
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
    const c = card(state, 0, MOCK_EVENTS[name])
    assert.ok(c.label.length > 0, name)
    const allowed = new Set([String(state.alert.limit_s), String(Math.floor(state.alert.still_s))])
    for (const n of `${c.title} ${c.detail} ${c.passedBy} ${c.tamper}`.match(/\d+/g) ?? []) assert.ok(allowed.has(n), `${name}: ${n}`)
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

// The board's messages, as the brain sends them (CONTRACTS.md section 5).
const armedState = (pred, extra = {}) => ({ ...MOCKS.armed, pred, ...extra })
const person = { present: true, kind: 'person', zone: 2, zone_set: [2], motion: 'moving' }
let seq = 0
const event = (kind, info = {}, id = `e${++seq}`) => ({ v: 2, type: 'event', t: 1763149512200, seq, src: 'live', id, kind, info })

// What the page does with each message (phone.js): a state replaces the state, an event goes to takeEvent.
function play(messages) {
  let state = null
  let events = noEvents()
  let chimes = 0
  for (const [at, msg] of messages) {
    if (isState(msg)) {
      state = msg
      events = followState(events, msg)
    } else {
      const next = takeEvent(events, msg, at)
      events = next.events
      if (next.chime && state?.armed === true) chimes += 1
    }
  }
  return { events, chimes, at: (now) => card(state, 0, events, now) }
}

test('armed: the card says Armed. and never all clear without a prediction', () => {
  const armed = show('armed')
  assert.deepEqual([armed.mode, armed.label, armed.title], ['armed', 'ARMED', 'Armed.'])
  const notReady = card({ ...MOCKS.armed, pred: null }, 0)
  assert.equal(notReady.label, 'ARMED')
  assert.match(notReady.detail, /cannot say the space is empty/)
  assert.equal(card({ ...MOCKS.intrusion, armed: false }, 0).mode, 'calm') // not armed: a person is just calm
})

test('a person in pred with no event: nothing is raised, however long they stay', () => {
  const run = play(Array.from({ length: 50 }, (_, i) => [i * 100, armedState(person)]))
  const c = run.at(5000)
  assert.deepEqual([c.mode, c.label, c.title, c.passedBy], ['armed', 'ARMED', 'Armed.', ''])
  assert.equal(run.chimes, 0)
  assert.equal(card(MOCKS.intrusion, 0).mode, 'armed') // the intrusion mock without its event
})

test('the intrusion event: the card, the zone, and one chime', () => {
  const e = event('intrusion', { zone: 2 })
  const run = play([[0, armedState(null)], [100, armedState(person)], [3500, e], [3600, armedState(person)], [3700, e]])
  const c = run.at(3700)
  assert.deepEqual([c.mode, c.label, c.title, c.zone], ['intrusion', 'INTRUSION', 'Someone is in the Chair zone.', 'Chair'])
  assert.equal(run.chimes, 1) // the same event twice rings once
  assert.equal(show('intrusion').mode, 'intrusion')
})

test('an intrusion stays when the person leaves and when the sensor goes blind', () => {
  const run = play([[0, armedState(person)], [3500, event('intrusion', { zone: 2 })], [4000, armedState(MOCKS.empty.pred)],
    [5000, { ...MOCKS.armed, health: { status: 'blind', blind: [], reason: 'rate' }, pred: null }]])
  assert.equal(run.at(5000).mode, 'intrusion')
  const hall = play([[0, MOCKS.armed], [100, event('intrusion', { link: 'h>unoq:ble' })]])
  assert.equal(hall.at(100).title, 'Someone is on a hall path.')
})

test('a second intrusion (a new event id) rings again; a feed coming back does not', () => {
  const run = play([[0, MOCKS.armed], [100, event('intrusion', { zone: 2 })], [200, event('intrusion', { zone: 1 })]])
  assert.equal(run.chimes, 2)
  assert.equal(shouldChime('nodata', 'intrusion'), false)
  assert.equal(shouldChime('armed', 'intrusion'), false) // the intrusion chime is the event's, not the card's
})

test('passed_by: one calm line, no alarm, no chime, gone after a few seconds', () => {
  const run = play([[0, armedState(person)], [2000, event('passed_by', { zone: 2 })], [2100, armedState(MOCKS.empty.pred)]])
  const c = run.at(2100)
  assert.deepEqual([c.mode, c.label, c.title, c.passedBy], ['armed', 'ARMED', 'Armed.', 'Someone passed by in the Chair zone.'])
  assert.equal(run.chimes, 0)
  assert.equal(run.at(2000 + PASSED_BY_MS).passedBy, '')
  const before = { ...ZONES }
  useZones({ zones: [{ id: 1, side: 'W', name: 'Left' }, { id: 2, side: 'E', name: 'Right' }] })
  assert.equal(run.at(2100).passedBy, 'Someone passed by on the right.')
  assert.equal(play([[0, MOCKS.armed], [1, event('passed_by', {})]]).at(1).passedBy, 'Someone passed by.')
  useZones({ zones: Object.entries(before).map(([id, name]) => ({ id: Number(id), name })) })
  assert.equal(show('passed').passedBy, 'Someone passed by in the Chair zone.')
})

test('disarmed, reset, or a state that is no longer armed clears the intrusion', () => {
  const ends = [
    [[200, event('disarmed')], [300, { ...MOCKS.armed, armed: false }]],
    [[200, event('reset')]],
    [[200, { ...MOCKS.armed, armed: false }]],
  ]
  for (const end of ends) {
    const run = play([[0, MOCKS.armed], [100, event('intrusion', { zone: 2 })], ...end, [400, MOCKS.armed]])
    assert.deepEqual(run.events, noEvents())
    assert.equal(run.at(400).mode, 'armed')
  }
})

test('a phone that joins late shows Armed. until the next event, never a guessed alarm', () => {
  // The intrusion was raised before this page connected. The state carries no intrusion, so the page cannot know.
  const late = play([[0, armedState(person)], [100, armedState(person)]])
  assert.deepEqual([late.at(100).mode, late.at(100).title, late.chimes], ['armed', 'Armed.', 0])
  const next = play([[0, armedState(person)], [100, event('intrusion', { zone: 2 })]])
  assert.equal(next.at(100).mode, 'intrusion')
  // An event that comes before the first state is kept, and the card follows that state.
  const first = play([[0, event('intrusion', { zone: 2 })], [100, armedState(person)]])
  assert.equal(first.at(100).mode, 'intrusion')
})

test('tamper: the device by its nodes.json name, only while armed, through a blind sensor', () => {
  assert.equal(tamperText({ tamper: ['east'] }), 'A device unplugged while armed.') // before nodes.json loads
  // The desk file by name (it has the east beacon), so the test holds whichever layout radio/nodes.json is.
  useDevices(JSON.parse(readFileSync(new URL('../../../../radio/layouts/desk.json', import.meta.url), 'utf8')))
  const c = show('tamper')
  assert.deepEqual([c.mode, c.tamper], ['blind', 'East beacon unplugged while armed.'])
  assert.equal(tamperText({ tamper: ['east', 'west', 'h', 'east'] }), 'East beacon, West beacon and Hall beacon H unplugged while armed.')
  assert.equal(card({ ...MOCKS.tamper, armed: false }, 0).tamper, '')
  assert.equal(card(MOCKS.armed, 0).tamper, '')
  assert.equal(card(MOCKS.tamper, 2000).tamper, '') // no data: nothing from an old state
  useDevices(JSON.parse(readFileSync(new URL('../../../../radio/layouts/gate.json', import.meta.url), 'utf8')))
  assert.equal(tamperText({ tamper: ['pi5b'] }), 'Pi B unplugged while armed.') // one spot: the file's name, no beacon
})

test('only v2 events are taken, and other kinds change nothing', () => {
  assert.equal(isEvent(event('enter', { zone: 2 })), true)
  assert.equal(isEvent({ ...event('intrusion'), v: 1 }), false)
  const events = noEvents()
  assert.equal(takeEvent(events, event('enter', { zone: 2 }), 0).events, events)
  assert.equal(takeEvent(events, MOCKS.armed, 0).events, events)
})
