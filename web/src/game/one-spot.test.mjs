// One spot: a layout with a single zone named as a place ("At the desk"). The phone page and the game say
// "at the desk", never "in the At the desk zone", and never a side.
// Run with: node --test web/src/game/
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { card, MOCKS } from './phone/card.js'
import { judge, resultText } from './tally.js'
import { CORNERS, compass, placeName, useZones, zoneList, ZONES } from './zones.js'

const SPOT = { zones: [{ id: 1, name: 'At the desk', centre_m: [0.4, 0.3], still_alert_s: 10 }] }
const person = (motion) => ({ present: true, kind: 'person', zone: 1, zone_set: [1], motion })

function onTheSpot(run) {
  const before = [{ ...ZONES }, { ...CORNERS }]
  assert.equal(useZones(SPOT), true)
  try {
    run()
  } finally {
    for (const k of Object.keys(ZONES)) delete ZONES[k]
    for (const k of Object.keys(CORNERS)) delete CORNERS[k]
    Object.assign(ZONES, before[0])
    Object.assign(CORNERS, before[1])
  }
}

test('one spot: the list has one zone with no side, and a place name is said as it is', () => onTheSpot(() => {
  assert.deepEqual(zoneList(), [{ id: 1, name: 'At the desk', hint: '' }])   // no "Zone 1" under the only zone
  assert.equal(placeName(1), 'at the desk')
  assert.equal(placeName(2), null)
  assert.deepEqual(compass(), [])   // the router is at the desk on the gate: "South: the router" would be wrong
}))

test('a plain zone name still gets its words', () => {
  assert.equal(placeName(2), null) // "Chair"
  assert.equal(card(MOCKS.calm, 100).title, 'Someone is in the Chair zone.')
})

test('one spot: the phone card says "at the desk" and colours those words', () => onTheSpot(() => {
  const calm = card({ ...MOCKS.calm, pred: person('still') }, 100)
  assert.deepEqual([calm.title, calm.detail, calm.zone], ['Someone is at the desk.', 'Standing still.', 'at the desk'])
  assert.equal(calm.title.split(calm.zone).length, 2) // the page splits the title on these words
  // The intrusion card comes from the board's event, never from pred.
  const intrusion = card({ ...MOCKS.intrusion, pred: person('moving') }, 100, { intrusion: { id: 'sim:e1', zone: 1, link: null }, passedBy: null })
  assert.deepEqual([intrusion.mode, intrusion.title, intrusion.zone], ['intrusion', 'Someone is at the desk.', 'at the desk'])
  const alert = card({ ...MOCKS.alert, pred: person('still'), alert: { state: 'check_on', zone: 1, still_s: 10.4, limit_s: 10 } }, 100)
  assert.deepEqual([alert.title, alert.zone], ['No movement at the desk for 10 s.', 'at the desk'])
  for (const c of [calm, intrusion, alert]) assert.doesNotMatch(`${c.title} ${c.detail}`, /\b(left|right|side|zone)\b/i)
}))

test('one spot: the game result says where in the same words', () => onTheSpot(() => {
  const state = { v: 2, type: 'state', src: 'live', health: { status: 'ok' }, pred: person('still') }
  assert.equal(resultText(judge(state, 10, 1)), 'Found you at the desk.')
  const nobody = { ...state, pred: { present: false, kind: 'none', zone: 0, zone_set: [], motion: null } }
  assert.equal(resultText(judge(nobody, 10, 1)), 'You hid! Wi-Fi saw nobody, you were at the desk.')
}))
