import { describe, expect, it } from 'vitest'
import { placeScan, scanUrl } from './scan'

describe('scan placement', () => {
  it('puts the scan floor under the square, centred, by default', () => {
    const p = placeScan([0.2, -1.1, -2.5], [4.4, 1.3, 1.1])
    // floor centre to the origin, floor (min y) to 0
    ;[-2.3, 1.1, 0.7].forEach((v, i) => expect(p.inner[i]).toBeCloseTo(v))
    expect(p.outer[1]).toBeLessThan(0) // a little under the floor marks
    expect(p.outer[0]).toBe(0)
    expect(p.yaw).toBe(0)
    expect(p.scale).toBe(1)
    expect(p.cut).toBe(1.4)
  })

  it('applies room.json: offset east/north, yaw, scale and cut', () => {
    const p = placeScan([0, 0, 0], [2, 2, 2], { offset_m: [0.3, -0.2], yaw_deg: 90, scale: 0.98, cut_m: 1.2 })
    expect(p.outer[0]).toBeCloseTo(0.3) // east is +x
    expect(p.outer[2]).toBeCloseTo(0.2) // north is -z, so 0.2 m south is +0.2
    expect(p.yaw).toBeCloseTo(Math.PI / 2)
    expect(p.scale).toBe(0.98)
    expect(p.cut).toBe(1.2)
    expect(placeScan([0, 0, 0], [1, 1, 1], { scale: -2 }).scale).toBe(1)
  })
})

describe('which hall model to load', () => {
  it('gives hi the detailed model and pi the light one, each falling back to the other', () => {
    const both = { hi: 'models/hall-hi.glb', lo: 'models/hall-lo.glb', fit: {} }
    expect(scanUrl(both, 'hi')).toBe('models/hall-hi.glb')
    expect(scanUrl(both, 'pi')).toBe('models/hall-lo.glb')
    expect(scanUrl({ lo: 'models/room.glb', fit: {} }, 'hi')).toBe('models/room.glb')
    expect(scanUrl({ hi: 'models/hall-hi.glb', fit: {} }, 'pi')).toBe('models/hall-hi.glb')
    expect(scanUrl({ fit: {} }, 'hi')).toBeUndefined()
  })
})
