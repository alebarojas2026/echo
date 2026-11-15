import { afterEach, describe, expect, it, vi } from 'vitest'
import nodesJson from '../../../radio/nodes.json'
import * as frame from './frame'
import { loadLayout } from './layout'
import { DESK_LAYOUT } from './layouts.fixture'

// applyLayout changes module state, so the cases run in order on one copy of frame.ts. They pass whichever
// layout radio/nodes.json has (the square today, the desk after the contract PR #415).
const real = structuredClone(nodesJson) as unknown as typeof DESK_LAYOUT
const square = { ...structuredClone(real), frame: { size_m: [2, 2] } }

describe('layout from nodes.json', () => {
  it('refuses malformed files and changes nothing', () => {
    expect(frame.applyLayout(null)).toBe(false)
    expect(frame.applyLayout({ v: 1, nodes: [] })).toBe(false)
    expect(frame.applyLayout({ ...real, nodes: real.nodes.filter((n) => n.id !== 'unoq') })).toBe(false) // links name a missing node
    expect(frame.applyLayout({ ...real, frame: { size_m: [0] } })).toBe(false)
    expect(frame.applyLayout({ ...DESK_LAYOUT, frame: { ...DESK_LAYOUT.frame, zone_split_x_m: 2 } })).toBe(false)
    expect(frame.applyLayout({ ...DESK_LAYOUT, zones: DESK_LAYOUT.zones.slice(1) })).toBe(false)
    expect(frame.SIZE_M).toEqual([2, 2]) // still the built-in square
    expect(frame.spotName('S-W30')).toBe('30 cm W')
  })

  it('accepts the repo file as it is: every node, link and zone from the file', () => {
    expect(frame.applyLayout(real)).toBe(true)
    expect(frame.SIZE_M).toEqual(real.frame.size_m)
    expect(Object.keys(frame.NODES)).toEqual(real.nodes.map((n) => n.id))
    expect(frame.LINK_IDS).toEqual(real.links.map((l) => l.id))
    expect(frame.ZONES.map((z) => z.id)).toEqual(real.zones.map((z) => z.id))
    for (const n of real.nodes) expect(frame.NODES[n.id].xyz).toEqual(n.xyz_m)
  })

  it('reads the desk layout: five named devices, twelve links, a strip with two zones', () => {
    expect(frame.applyLayout(DESK_LAYOUT)).toBe(true)
    expect(frame.SIZE_M).toEqual([1.6, 1.1])
    expect(frame.STRIP_M).toEqual([1.6, 0.6])
    expect(frame.floorSize()).toEqual([1.6, 0.6])
    expect(Object.values(frame.NODES).map((n) => n.name)).toEqual(['Board', 'Pi A', 'Pi B', 'East beacon', 'West beacon'])
    expect(frame.LINK_IDS).toHaveLength(12)
    expect(frame.parseLinkId('pi5b>pi5:ble')).toEqual({ tx: 'pi5b', rx: 'pi5', kind: 'ble' })
    expect(frame.routerId()).toBe('pi5')
    // zone = 1 + (x >= 0.8) inside the strip, 0 anywhere else (the desk top is never a zone)
    expect(frame.zoneAt(0.3, 0.3)).toBe(1)
    expect(frame.zoneAt(0.8, 0.3)).toBe(2)
    expect(frame.zoneAt(1.2, 0.9)).toBe(0)
    expect(frame.zoneAt(-0.1, 0.3)).toBe(0)
    expect(frame.zoneCenter(2)).toEqual([1.2, 0.3])
    expect(frame.zoneRect(1)).toEqual([0, 0, 0.8, 0.6])
    expect(frame.zoneCenter(3)).toBeNull()
    // the layout's centre is the scene's origin
    expect(frame.toScene([0.8, 0.55, 0])).toEqual([0, 0, 0])
    expect(frame.nodePosition('pi5', 'S-W30')).toEqual([0.5, 1.1, 1])
    expect(frame.nodeLabelSide('west')).toBe('below-right')
    expect(frame.nodeLabelSide('pi5')).toBe('above')
    expect(frame.TRAY_SPOTS[0]).toEqual([0.86, 1.0, 1.0])
  })

  it('follows a moved device with no code change', () => {
    const moved = structuredClone(DESK_LAYOUT)
    moved.nodes[2].xyz_m = [0.4, 0.7, 1.0]
    expect(frame.applyLayout(moved)).toBe(true)
    expect(frame.nodePosition('pi5b', 'S-home')).toEqual([0.4, 0.7, 1.0])
  })

  it('follows a 1.5 m square and gate-7 router spots without a rebuild', () => {
    const s = 0.75
    const small = {
      ...square,
      frame: { size_m: [1.5, 1.5] },
      nodes: square.nodes.map((n) => ({ ...n, xyz_m: [n.xyz_m[0] * s, n.xyz_m[1] * s, 1.0] })),
      router_spots: [
        { id: 'S-home', xyz_m: [0.75, 0, 1] },
        { id: 'S-W20', xyz_m: [0.55, 0, 1] },
      ],
      zones: [
        { id: 1, name: 'Bed' },
        { id: 2, name: 'Desk' },
        { id: 3, name: 'Hall' },
        { id: 4, name: 'Bathroom' },
      ],
    }
    expect(frame.applyLayout(small)).toBe(true)
    expect(frame.SIZE_M).toEqual([1.5, 1.5])
    expect(frame.STRIP_M).toBeNull()
    expect(frame.zoneAt(0.8, 0.8)).toBe(2) // the zone line moves to 0.75 m
    expect(frame.zoneCenter(4)).toEqual([1.125, 0.375])
    expect(frame.toScene([0.75, 0.75, 0])).toEqual([0, 0, 0])
    expect(Object.keys(frame.ROUTER_SPOTS)).toEqual(['S-home', 'S-W20'])
    expect(frame.nodePosition('pi5', 'S-W20')).toEqual([0.55, 0, 1])
    expect(frame.spotName('S-W20')).toBe('20 cm W')
    expect(frame.spotName('S-home')).toBe('home')
    expect(frame.ZONES.find((z) => z.id === 2)!.name).toBe('Desk')
  })
})

describe('when /nodes.json cannot be read', () => {
  afterEach(() => vi.unstubAllGlobals())
  const reply = (status: number, body: unknown) => () => Promise.resolve({ ok: status === 200, json: () => Promise.resolve(body) })
  /** Some other layout on screen first, so the fallback is seen to replace it. */
  const other = () => {
    const moved = structuredClone(DESK_LAYOUT)
    moved.frame.strip_m = [1.2, 0.6]
    moved.frame.zone_split_x_m = 0.6
    moved.nodes[2].name = 'Elsewhere'
    return frame.applyLayout(moved)
  }

  it('uses the file when it is served', async () => {
    vi.stubGlobal('fetch', reply(200, real))
    expect(await loadLayout('/nodes.json', 50, DESK_LAYOUT)).toBe('nodes.json')
    expect(frame.LINK_IDS).toEqual(real.links.map((l) => l.id))
  })

  it('falls back to the layout the page was built with, not the old square: offline, not found, or malformed', async () => {
    for (const fetch of [() => Promise.reject(new Error('offline')), reply(404, null), reply(200, { v: 2, nodes: 'none' })]) {
      expect(other()).toBe(true)
      vi.stubGlobal('fetch', fetch)
      expect(await loadLayout('/nodes.json', 50, DESK_LAYOUT)).toBe('contract')
      expect(frame.STRIP_M).toEqual([1.6, 0.6])
      expect(frame.NODES.pi5b.name).toBe('Pi B')
    }
  })

  it('carries radio/nodes.json in the build as that fallback', async () => {
    expect(__BUILD_LAYOUT__).toEqual(nodesJson)
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')))
    expect(other()).toBe(true)
    expect(await loadLayout()).toBe('contract')
    expect(frame.LINK_IDS).toEqual(real.links.map((l) => l.id))
  })
})
