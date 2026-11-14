// Run with: node --test web/src/game/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { CORNERS, loadZones, useZones, zoneList, ZONES } from './zones.js'

const saved = () => [{ ...ZONES }, { ...CORNERS }]
const restore = ([z, c]) => {
  useZones({ zones: Object.entries(z).map(([id, name]) => ({ id: Number(id), name, corner: c[id] })) })
}

test("main's nodes.json gives the contract's four zones in floor order", () => {
  const before = saved()
  const nodes = JSON.parse(readFileSync(new URL('../../../radio/nodes.json', import.meta.url), 'utf8'))
  assert.equal(useZones(nodes), true)
  assert.deepEqual(zoneList(), [
    { id: 1, name: 'Bed', hint: 'Zone 1, north-west' }, { id: 2, name: 'Chair', hint: 'Zone 2, north-east' },
    { id: 3, name: 'Hall', hint: 'Zone 3, south-west' }, { id: 4, name: 'Bathroom', hint: 'Zone 4, south-east' }])
  restore(before)
})

test('a new layout replaces the zones; a file without zones changes nothing', async () => {
  const before = saved()
  assert.equal(useZones({ zones: [{ id: 2, name: 'Sofa' }, { id: 1, name: 'Desk ' }] }), true)
  assert.deepEqual(ZONES, { 1: 'Desk', 2: 'Sofa' })
  assert.deepEqual(zoneList().map((z) => z.hint), ['Zone 1', 'Zone 2'])
  assert.equal(useZones({ zones: [] }), false)
  assert.equal(useZones(null), false)
  assert.deepEqual(ZONES, { 1: 'Desk', 2: 'Sofa' })
  assert.equal(await loadZones(async () => { throw new Error('offline') }), false)
  assert.equal(await loadZones(async () => ({ ok: false })), false)
  assert.equal(await loadZones(async () => ({ ok: true, json: async () => ({ zones: [{ id: 1, name: 'Hall' }] }) })), true)
  assert.deepEqual(ZONES, { 1: 'Hall' })
  restore(before)
})

test('the desk strip: zones with a side, west first', () => {
  const before = saved()
  useZones({ zones: [{ id: 2, side: 'E', name: 'Bathroom', still_alert_s: 10 }, { id: 1, side: 'W', name: 'Living room', still_alert_s: null }] })
  assert.deepEqual(zoneList(), [{ id: 1, name: 'Living room', hint: 'Zone 1, west' }, { id: 2, name: 'Bathroom', hint: 'Zone 2, east' }])
  restore(before)
})
