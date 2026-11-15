import { describe, expect, it } from 'vitest'
import type { HallLink } from './contract'
import { hallHeard, trayText } from './devices'
import { HALL_BEACONS, applyLayout } from './frame'
import { cleanPositions, setHallBeaconPositions } from './hallfile'
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
