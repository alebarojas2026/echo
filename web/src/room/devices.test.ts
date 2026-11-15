import { describe, expect, it } from 'vitest'
import type { HallLink } from './contract'
import { hallHeard, trayText } from './devices'
import { HALL_BEACONS, applyLayout } from './frame'
import { cleanNodePositions, cleanPositions, setHallBeaconPositions, setNodePositions } from './hallfile'
import { DESK_LAYOUT } from './layouts.fixture'
import { mockState } from './mock'

const row = (tx: string, rate: number, stale = false): HallLink => ({ id: `${tx}>unoq:ble`, tx, rx: 'unoq', xy_m: null, activity: 0, moving: false, rate_hz: rate, stale })

// How the hall beacon lines look in radio/nodes.json (contract PR #415): one object per line.
const FILE = `{
  "beacons": {
    "payloads": [
      {"node": "pi5", "id": "S", "data_hex": "FFFF525353"},
      {"node": "east", "id": "E", "data_hex": "FFFF525345"}
    ]
  },
  "hall": {
    "beacons": [
      {"node": "h", "id": "H", "data_hex": "FFFF525348", "xyz_m": null},
      {"node": "j", "id": "J", "data_hex": "FFFF52534A", "xyz_m": null}
    ]
  }
}
`

describe('hall beacons', () => {
  it('are heard only with readings, never when stale', () => {
    expect([...hallHeard([row('h', 6.5), row('j', 0), row('k', 6, true)])]).toEqual(['h'])
    expect(hallHeard(undefined).size).toBe(0) // a missing hall reads as []
  })

  it('wait in the tray, named by their letters, until someone places them', () => {
    expect(trayText([])).toBe('')
    expect(trayText([{ node: 'h', id: 'H', xyz: null }])).toBe('1 new beacon: H')
    expect(trayText([{ node: 'h', id: 'H', xyz: null }, { node: 'j', id: 'J', xyz: null }])).toBe('2 new beacons: H, J')
  })

  it('come from nodes.json, placed or not, and a bad one never sinks the file', () => {
    const hall = { beacons: [...DESK_LAYOUT.hall.beacons, { node: 'unoq' }, { id: 'X' }] }
    expect(applyLayout({ ...DESK_LAYOUT, hall })).toBe(true)
    expect(HALL_BEACONS).toEqual([{ node: 'h', id: 'H', xyz: null }, { node: 'j', id: 'J', xyz: null }])
  })

  it('save into nodes.json by changing only their xyz_m, and a reload reads them back', () => {
    const saved = setHallBeaconPositions(FILE, [{ node: 'h', xyz_m: [14, 9.5, 1] }, { node: 'j', xyz_m: null }])
    expect(saved).toBe(FILE.replace('"FFFF525348", "xyz_m": null', '"FFFF525348", "xyz_m": [14, 9.5, 1]'))
    expect(JSON.parse(saved).hall.beacons[0].xyz_m).toEqual([14, 9.5, 1])
    const moved = structuredClone(DESK_LAYOUT)
    moved.hall.beacons[0].xyz_m = JSON.parse(saved).hall.beacons[0].xyz_m
    expect(applyLayout(moved)).toBe(true)
    expect(HALL_BEACONS[0].xyz).toEqual([14, 9.5, 1])
    // moving it again replaces the numbers, not adds to them
    expect(setHallBeaconPositions(saved, [{ node: 'h', xyz_m: [2, 3, 1] }])).toContain('"xyz_m": [2, 3, 1]}')
  })

  it('save only well-formed positions', () => {
    expect(cleanPositions([{ node: 'h', xyz_m: [1, 2, 1] }, { node: 'j', xyz_m: null }])).toHaveLength(2)
    expect(cleanPositions([{ node: 'h', xyz_m: [1, 2] }])).toBeNull()
    expect(cleanPositions([{ node: 'h"', xyz_m: null }])).toBeNull()
    expect(cleanPositions({ node: 'h' })).toBeNull()
  })

  it('in ?mock=power: J is off for the first 4 s of each cycle, then heard (with no position: the tray)', () => {
    applyLayout(DESK_LAYOUT)
    expect([...hallHeard(mockState('power', 1, 1000).hall)]).toEqual(['h'])
    expect([...hallHeard(mockState('power', 1, 5000).hall)]).toEqual(['h', 'j'])
    expect(mockState('power', 1, 5000).hall!.every((r) => r.xy_m === null)).toBe(true)
  })
})

describe('saving where the devices were placed', () => {
  // The lines of radio/nodes.json that matter here, one object a line as the file has them.
  const NODES_FILE = `{
  "nodes": [
    {"id": "unoq", "name": "Board", "xyz_m": [1.1, 0.6, 1.0], "roles": ["receiver"]},
    {"id": "pi5", "name": "Pi A", "xyz_m": [0.8, 1.1, 1.0], "roles": ["router", "beacon", "receiver"]},
    {"id": "pi5b", "name": "Pi B", "xyz_m": [0.5, 0.6, 1.0], "roles": ["beacon", "receiver"]}
  ],
  "links": [
    {"id": "pi5>unoq:wifi", "tx": "pi5", "rx": "unoq", "kind": "wifi", "expected_hz": null}
  ],
  "router_spots": [
    {"id": "S-home", "xyz_m": [0.8, 1.1, 1.0]},
    {"id": "S-W30", "xyz_m": [0.5, 1.1, 1.0]}
  ],
  "tray_spots": [
    {"id": "T1", "xyz_m": [0.86, 1.0, 1.0]}
  ],
  "beacons": {"payloads": [{"node": "pi5", "id": "S", "data_hex": "FFFF525353"}]},
  "hall": {"beacons": [{"node": "h", "id": "H", "data_hex": "FFFF525348", "xyz_m": null}]}
}
`

  it('changes only the placed devices\u2019 xyz_m, one line each, and the file still parses', () => {
    const saved = setNodePositions(NODES_FILE, [{ id: 'pi5b', xyz_m: [0.8, -0.38, 0.94] }])
    expect(saved).toContain('{"id": "pi5b", "name": "Pi B", "xyz_m": [0.8, -0.38, 0.94], "roles": ["beacon", "receiver"]}')
    const changed = saved.split('\n').filter((line, i) => line !== NODES_FILE.split('\n')[i])
    expect(changed).toHaveLength(1)
    expect(JSON.parse(saved).nodes[2].xyz_m).toEqual([0.8, -0.38, 0.94])
  })

  it('moves the router\u2019s spots and the tray with the router, so S-home is where the router is', () => {
    const saved = JSON.parse(setNodePositions(NODES_FILE, [{ id: 'pi5', xyz_m: [0.76, 0.68, 0.8] }]))
    expect(saved.nodes[1].xyz_m).toEqual([0.76, 0.68, 0.8])
    expect(saved.router_spots).toEqual([{ id: 'S-home', xyz_m: [0.76, 0.68, 0.8] }, { id: 'S-W30', xyz_m: [0.46, 0.68, 0.8] }])
    // the tray takes its own place, 12 cm from the router toward the board, never carried off the desk's edge
    expect(saved.tray_spots[0].xyz_m).toEqual([0.877, 0.653, 0.8])
    expect(saved.hall.beacons[0].xyz_m).toBeNull() // nothing else is touched
    expect(saved.beacons.payloads[0]).toEqual({ node: 'pi5', id: 'S', data_hex: 'FFFF525353' })
  })

  it('places the tray from where both ended up when the router and the board are saved together', () => {
    const saved = JSON.parse(setNodePositions(NODES_FILE, [{ id: 'unoq', xyz_m: [0.84, 0.68, 0.8] }, { id: 'pi5', xyz_m: [0.76, 0.68, 0.8] }]))
    expect(saved.tray_spots[0].xyz_m).toEqual([0.8, 0.68, 0.8]) // halfway between them, 8 cm apart
  })

  it('leaves out a device the file does not have', () => {
    expect(setNodePositions(NODES_FILE, [{ id: 'east', xyz_m: [1, 1, 1] }])).toBe(NODES_FILE)
  })

  it('takes only well-formed positions', () => {
    expect(cleanNodePositions([{ id: 'pi5b', xyz_m: [0.8, -0.38, 0.94] }])).toHaveLength(1)
    expect(cleanNodePositions([{ id: 'S-home', xyz_m: [0, 0, 1] }])).toBeNull()
    expect(cleanNodePositions([{ id: 'pi5b', xyz_m: [0, 0, 4] }])).toBeNull()
    expect(cleanNodePositions([{ id: 'pi5b', xyz_m: [0, 9, 1] }])).toBeNull()
    expect(cleanNodePositions([{ id: 'pi5b', xyz_m: [0, 0] }])).toBeNull()
    expect(cleanNodePositions({})).toBeNull()
  })
})
