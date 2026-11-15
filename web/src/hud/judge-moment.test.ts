import { expect, test } from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import old from '../../../radio/nodes.json'
import { mockState } from './mock-layout'
import { judgeMoment } from './judge-moment'
import { linkName, zonePlace } from './layout'

test('desk headlines use configured sides and preserve distinct unavailable states', () => {
  const state = mockState('still', 0, 7000)
  for (const [zone, side] of [[desk.zones[0].id, 'left'], [desk.zones[1].id, 'right']] as const) {
    for (const motion of ['moving', 'still'] as const) {
      state.pred = { ...state.pred!, zone, zone_set: [zone], kind: 'person', motion }
      expect(judgeMoment(state, false, desk)[0]).toBe(`${motion === 'moving' ? 'Moving' : 'Still'} on the ${side}`)
    }
  }
  state.pred!.zone_set = desk.zones.map(z => z.id)
  expect(judgeMoment(state, false, desk)).toEqual(['Between two zones', 'Left or Right'])
  for (const [scenario, heading] of [['empty', 'Nobody is here'], ['object', 'Dead zone found'], ['blind', 'Sensor blind']] as const) expect(judgeMoment(mockState(scenario, 0, 1000), false, desk)[0]).toBe(heading)
  // An object the board has no advice about (the first seconds, or one away from the router's link) is just an object.
  expect(judgeMoment({ ...mockState('object', 0, 1000), advice: null }, false, desk)[0]).toBe('An object, not a person')
  expect(judgeMoment(null, true, desk)[0]).toBe('No data')
  state.pred = null
  state.model!.trained = false
  expect(judgeMoment(state, false, desk)[0]).toBe('Not trained yet')
  state.model!.trained = true
  expect(judgeMoment(state, false, desk)[0]).toBe('Recalibrating')
  state.router = 'S-W30'
  expect(judgeMoment(state, false, desk)[0]).toBe('Paused')
})
test('link words use every configured node and retain an unnamed fallback', () => {
  for (const link of desk.links) {
    const tx = desk.nodes.find(n => n.id === link.tx)!.name
    const rx = desk.nodes.find(n => n.id === link.rx)!.name
    expect(linkName(link.id, desk)).toBe(`${tx} to ${rx}, ${link.kind === 'wifi' ? 'Wi-Fi' : 'Bluetooth'}`)
  }
  expect(linkName('east>pi5b:ble', desk)).toBe('East beacon to Pi B, Bluetooth')
  expect(linkName('pi5>unoq:wifi', { ...old, nodes: old.nodes.map(n => ({ ...n, name: undefined })) })).toBe('pi5 to unoq, Wi-Fi')
  expect(zonePlace(999, desk)).toBe('at the desk')
})
