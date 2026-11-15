import { Box3, BoxGeometry, Mesh, Object3D, Vector3 } from 'three'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import {
  DEVICE_BOUNDS,
  DISPLAY_SCALE,
  NODE_HEIGHT_M,
  createDevice,
  deviceLabelPoint,
  deviceMaterials,
  devicesLoaded,
  setDeviceHeight,
  setDeviceAppearance,
  type DeviceKind,
} from './devices'

// The real model files, read from disk: vite turns './assets/x.glb?url' into '/src/room/assets/x.glb'.
// Node's file reader is imported by name, so this browser project's tsconfig needn't know node's types.
const fsModule = 'node:fs/promises'
const { readFile } = (await import(/* @vite-ignore */ fsModule)) as { readFile(path: URL): Promise<Uint8Array<ArrayBuffer>> }
const WEB = new URL('../../', import.meta.url)

beforeAll(() => {
  vi.stubGlobal('fetch', async (url: string) => {
    try {
      return new Response(await readFile(new URL(`.${url}`, WEB)))
    } catch {
      return new Response(null, { status: 404 })
    }
  })
})
afterAll(() => vi.unstubAllGlobals())

const KINDS: DeviceKind[] = ['unoq', 'pi5', 'phone']

/** Builds a device and waits until its model has been drawn into it. */
async function ready(kind: DeviceKind): Promise<{ device: Object3D; loaded: boolean }> {
  let loaded = false
  const device = await new Promise<Object3D>((resolve) => {
    const d = createDevice(kind, (ok) => {
      loaded = ok
      resolve(d)
    })
  })
  return { device, loaded }
}

function meshes(root: Object3D): Mesh[] {
  const out: Mesh[] = []
  root.traverse((o) => {
    if (o instanceof Mesh) out.push(o)
  })
  return out
}

function triangles(root: Object3D): number {
  return meshes(root).reduce((n, m) => n + (m.geometry.index?.count ?? m.geometry.getAttribute('position').count) / 3, 0)
}

/** The device's model (not its stand) in real metres around its anchor, whatever the nodes above it do. */
function modelBox(device: Object3D): Box3 {
  const head = device.getObjectByName('head')!
  device.updateMatrixWorld(true)
  const toHead = head.matrixWorld.clone().invert()
  const box = new Box3()
  for (const m of meshes(head)) {
    m.geometry.computeBoundingBox()
    box.union(m.geometry.boundingBox!.clone().applyMatrix4(toHead.clone().multiply(m.matrixWorld)))
  }
  return box
}

describe('createDevice', () => {
  it('returns an object right away, origin on the floor, anchor at the node height', () => {
    const device = createDevice('pi5')
    device.updateMatrixWorld(true)
    expect(device.name).toBe('device-pi5')
    const anchor = device.getObjectByName('anchor')!
    expect(anchor.getWorldPosition(new Vector3()).toArray()).toEqual([0, NODE_HEIGHT_M, 0])
  })

  it.each(KINDS)('loads %s from its file with the shared materials', async (kind) => {
    const { device, loaded } = await ready(kind)
    expect(loaded).toBe(true)
    const shared = Object.values(deviceMaterials())
    const parts = meshes(device)
    expect(parts.length).toBeGreaterThanOrEqual(3) // the model, the foot and the pole
    for (const m of parts) {
      expect(shared).toContain(m.material)
      expect(m.geometry.getAttribute('uv')).toBeUndefined()
      expect(m.geometry.getAttribute('color')).toBeDefined() // the baked occlusion
    }
    expect(device.getObjectByName('anchor')).toBeDefined()
    expect(device.getObjectByName('mount')).toBeUndefined()
  })

  it('shares geometry between copies, so the two phones cost one', async () => {
    const [a, b] = await Promise.all([ready('phone'), ready('phone')])
    const ga = meshes(a.device).map((m) => m.geometry)
    const gb = meshes(b.device).map((m) => m.geometry)
    expect(ga).toEqual(gb)
    for (let i = 0; i < ga.length; i++) expect(ga[i]).toBe(gb[i])
  })

  it.each(KINDS)('keeps %s under the triangle budget', async (kind) => {
    const { device } = await ready(kind)
    expect(triangles(device.getObjectByName('head')!)).toBeLessThanOrEqual(1500)
  })

  it('keeps the stand light too', async () => {
    const { device } = await ready('unoq')
    const head = device.getObjectByName('head')!
    expect(triangles(device) - triangles(head)).toBeLessThanOrEqual(600)
  })
})

describe('the models', () => {
  it.each(KINDS)('match DEVICE_BOUNDS for %s within a millimetre', async (kind) => {
    const { device } = await ready(kind)
    const box = modelBox(device)
    const { min, max } = DEVICE_BOUNDS[kind]
    for (let i = 0; i < 3; i++) {
      expect(box.min.getComponent(i)).toBeCloseTo(min[i], 3)
      expect(box.max.getComponent(i)).toBeCloseTo(max[i], 3)
    }
  })

  it('are real size: the UNO Q board, the Pi 5 case and the phone', async () => {
    const size = async (kind: DeviceKind) => modelBox((await ready(kind)).device).getSize(new Vector3()).multiplyScalar(1000)
    const unoq = await size('unoq')
    expect(unoq.x).toBeCloseTo(68.58 + 0.6, 0) // the board, plus the USB-C shell standing 0.6 mm proud
    const pi5 = await size('pi5')
    expect(pi5.x).toBeCloseTo(70.3, 0)
    expect(pi5.z).toBeCloseTo(98.5, 0)
    const phone = await size('phone')
    expect(phone.x).toBeGreaterThan(71.5) // the body, plus its side buttons
    expect(phone.x).toBeLessThan(74)
  })

  it('lean back, so their faces turn towards the front (+z) and up', async () => {
    for (const kind of ['unoq', 'phone'] as DeviceKind[]) {
      const head = (await ready(kind)).device.getObjectByName('head')!
      // the highest point of a leaning board or phone is behind its centre
      let top = new Vector3(0, -Infinity, 0)
      for (const m of meshes(head)) {
        const pos = m.geometry.getAttribute('position')
        for (let i = 0; i < pos.count; i++) {
          if (pos.getY(i) > top.y) top = new Vector3().fromBufferAttribute(pos, i)
        }
      }
      expect(top.z).toBeLessThan(0)
    }
  })
})

describe('setDeviceHeight', () => {
  it('moves the anchor to the height and stretches the pole to the mount', async () => {
    const { device } = await ready('phone')
    setDeviceHeight(device, 1.2)
    device.updateMatrixWorld(true)
    expect(device.getObjectByName('anchor')!.getWorldPosition(new Vector3()).y).toBeCloseTo(1.2, 6)
    const pole = device.getObjectByName('pole') as Mesh
    const foot = device.getObjectByName('foot') as Mesh
    const poleBox = new Box3().setFromObject(pole)
    const headBox = new Box3().setFromObject(device.getObjectByName('head')!)
    expect(poleBox.min.y).toBeCloseTo(0, 6)
    // the pole ends a few millimetres into the device's socket, the lowest part of the device
    expect(poleBox.max.y - headBox.min.y).toBeGreaterThan(0)
    expect(poleBox.max.y - headBox.min.y).toBeLessThan(0.02)
    expect(new Box3().setFromObject(foot).min.y).toBeCloseTo(0, 6)
    expect(foot.scale.x).toBe(DISPLAY_SCALE)
  })

  it('takes a height set before the file has loaded, as the stage does', async () => {
    const device = await new Promise<Object3D>((resolve) => {
      const d = createDevice('unoq', () => resolve(d))
      setDeviceHeight(d, 0.8)
    })
    device.updateMatrixWorld(true)
    expect(device.getObjectByName('anchor')!.getWorldPosition(new Vector3()).y).toBeCloseTo(0.8, 6)
    const poleTop = new Box3().setFromObject(device.getObjectByName('pole')!).max.y
    const headBottom = new Box3().setFromObject(device.getObjectByName('head')!).min.y
    expect(poleTop - headBottom).toBeGreaterThan(0)
    expect(poleTop - headBottom).toBeLessThan(0.02)
  })
})

describe('deviceLabelPoint', () => {
  it('puts a name above the device or just past its side, whichever way it faces', () => {
    const device = createDevice('phone')
    device.position.set(1, 0, 0)
    device.rotation.y = -Math.PI / 2 // the east phone, facing the centre (west)
    const right = deviceLabelPoint(device, 'right')
    const left = deviceLabelPoint(device, 'left')
    const above = deviceLabelPoint(device, 'above')
    const { min, max } = DEVICE_BOUNDS.phone
    expect(right.y).toBeCloseTo(NODE_HEIGHT_M, 6)
    expect(right.x).toBeCloseTo(1 - min[2] * DISPLAY_SCALE, 6) // its back faces east
    expect(left.x).toBeCloseTo(1 - max[2] * DISPLAY_SCALE, 6)
    expect(above.toArray()).toEqual([1, NODE_HEIGHT_M + max[1] * DISPLAY_SCALE, 0])
  })
})

describe('when a file is missing', () => {
  it('draws a plain box of the right size and says so', async () => {
    vi.resetModules()
    vi.stubGlobal('fetch', async () => new Response(null, { status: 404 }))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const fresh = await import('./devices')
    let device: Object3D | null = null
    const loaded = await new Promise<boolean>((resolve) => {
      device = fresh.createDevice('unoq', resolve)
    })
    expect(loaded).toBe(false)
    expect(warn).toHaveBeenCalled()
    device!.updateMatrixWorld(true)
    const box = meshes(device!.getObjectByName('head')!)[0]
    expect(box.geometry).toBeInstanceOf(BoxGeometry)
    const size = new Box3().setFromObject(box).getSize(new Vector3()).divideScalar(DISPLAY_SCALE)
    const { min, max } = fresh.DEVICE_BOUNDS.unoq
    expect(size.x).toBeCloseTo(max[0] - min[0], 6)
    await fresh.devicesLoaded()
    warn.mockRestore()
  })
})

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


describe('desk devices', () => {
  it('keeps the antenna at its node while an arm reaches from the desk edge', async () => {
    const { device } = await ready('beacon')
    device.position.set(1, 1, 2)
    setDeviceHeight(device, 0, new Vector3(0, 0, .35))
    device.updateMatrixWorld(true)
    expect(device.getObjectByName('anchor')!.getWorldPosition(new Vector3()).toArray()).toEqual([1,1,2.35])
    const pole = device.getObjectByName('pole')!
    expect(pole.scale.y).toBeCloseTo(Math.hypot(.35, DEVICE_BOUNDS.beacon.min[1] * DISPLAY_SCALE))
    expect(triangles(device.getObjectByName('head')!)).toBeLessThan(200)
    expect(deviceLabelPoint(device, 'right').z).toBe(2.35)
  })

  it('fades and colours one node without changing another copy', async () => {
    const [a, b] = await Promise.all([ready('pi5'), ready('pi5')])
    setDeviceAppearance(a.device, .2, true)
    const material = meshes(a.device)[0].material as import('three').ShaderMaterial
    expect(material.uniforms.uAlpha.value).toBe(.2)
    expect(material.uniforms.uFault.value).toBe(1)
    expect(material.transparent).toBe(true)
    expect(material.depthWrite).toBe(false)
    const other = meshes(b.device)[0].material as import('three').ShaderMaterial
    expect(other.uniforms.uAlpha.value).toBe(1)
    expect(other.uniforms.uFault.value).toBe(0)
    expect(meshes(a.device)[0].geometry).toBe(meshes(b.device)[0].geometry)
    setDeviceAppearance(a.device, 1, false)
    expect(material.uniforms.uFault.value).toBe(0)
    expect(material.depthWrite).toBe(true)
  })
})
