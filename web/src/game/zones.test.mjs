// Run with: node --test web/src/game/
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import { compass, CORNERS, loadZones, useZones, zoneList, ZONES } from './zones.js'

const saved = () => [{ ...ZONES }, { ...CORNERS }]
const restore = ([z, c]) => {
  useZones({ zones: Object.entries(z).map(([id, name]) => ({ id: Number(id), name, corner: c[id] })) })
}

// What a zone's corner or side reads as, written out here so the test doesn't borrow the page's own table.
const WHERE = { NW: 'north-west', NE: 'north-east', SW: 'south-west', SE: 'south-east', W: 'west', E: 'east' }

test("the repo's nodes.json: every zone in the file is listed, with the file's name and place", () => {
  const before = saved()
  const nodes = JSON.parse(readFileSync(new URL('../../../radio/nodes.json', import.meta.url), 'utf8'))
  assert.ok(nodes.zones.length >= 1)   // one spot, or a row or a square of zones
  assert.equal(useZones(nodes), true)
  const want = nodes.zones.map((z) => ({ id: z.id, name: z.name, hint: WHERE[z.corner ?? z.side] ? `Zone ${z.id}, ${WHERE[z.corner ?? z.side]}` : `Zone ${z.id}` }))
  const byId = (a, b) => a.id - b.id
  assert.deepEqual([...zoneList()].sort(byId), want.sort(byId))
  assert.ok(zoneList().every((z) => !z.hint.includes('undefined')))
  const strip = nodes.zones.every((z) => z.side === 'W' || z.side === 'E')   // a spot with no side is not a row
  assert.deepEqual(compass(), strip ? ['West', 'East'] : ['South: the router', 'North is up'])
  restore(before)
})

test('the square: four zones with a corner, in floor order', () => {
  const before = saved()
  useZones({ zones: [{ id: 4, corner: 'SE', name: 'Bathroom' }, { id: 3, corner: 'SW', name: 'Hall' },
    { id: 1, corner: 'NW', name: 'Bed' }, { id: 2, corner: 'NE', name: 'Chair' }] })
  assert.deepEqual(zoneList(), [
    { id: 1, name: 'Bed', hint: 'Zone 1, north-west' }, { id: 2, name: 'Chair', hint: 'Zone 2, north-east' },
    { id: 3, name: 'Hall', hint: 'Zone 3, south-west' }, { id: 4, name: 'Bathroom', hint: 'Zone 4, south-east' }])
  assert.deepEqual(compass(), ['South: the router', 'North is up'])
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
  assert.deepEqual(compass(), ['West', 'East'])
  restore(before)
})
