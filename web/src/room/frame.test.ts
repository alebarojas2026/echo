import { describe, expect, it } from 'vitest'
import { LINK_IDS, nodePosition, parseLinkId, toScene, zoneAt, zoneCenter } from './frame'

describe('room frame', () => {
  it('maps the contract frame to the scene with north away from the viewer', () => {
    expect(toScene([0, 0, 0])).toEqual([-1, 0, 1]) // south-west corner
    expect(toScene([1, 2, 1])).toEqual([0, 1, -1]) // UNO Q, north, 1 m up
  })

  it('parses every contract link id', () => {
    for (const id of LINK_IDS) expect(parseLinkId(id)).not.toBeNull()
    expect(parseLinkId('east>pi5:ble')).toEqual({ tx: 'east', rx: 'pi5', kind: 'ble' })
    expect(parseLinkId('moon>pi5:ble')).toBeNull()
    expect(parseLinkId('garbage')).toBeNull()
  })

  it('agrees with the contract zone rule and centres', () => {
    expect(zoneAt(0.5, 1.5)).toBe(1)
    expect(zoneAt(1.5, 1.5)).toBe(2)
    expect(zoneAt(0.5, 0.5)).toBe(3)
    expect(zoneAt(1.42, 0.61)).toBe(4)
    for (const z of [1, 2, 3, 4]) {
      const c = zoneCenter(z)!
      expect(zoneAt(c[0], c[1])).toBe(z)
    }
    expect(zoneCenter(0)).toBeNull()
  })

  it('moves only the router with state.router', () => {
    expect(nodePosition('pi5', 'S-W30')).toEqual([0.7, 0, 1])
    expect(nodePosition('pi5', 'nowhere')).toEqual([1, 0, 1])
    expect(nodePosition('east', 'S-W30')).toEqual([2, 1, 1])
  })
})
