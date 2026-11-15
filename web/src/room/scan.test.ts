import { Box3, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { hallLift, placeScan, scanUrl, surfaceUnder } from './scan'

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

  it('lowers the model by floor_m, so a tier can be our floor', () => {
    expect(placeScan([0, 0, 0], [2, 2, 2]).outer[1]).toBeCloseTo(-0.03)
    expect(placeScan([0, 0, 0], [2, 2, 2], { floor_m: 0.312 }).outer[1]).toBeCloseTo(-0.342)
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

  it('picks a look to compare with ?hall=A, and the usual files for an unknown one or none', () => {
    const src = { hi: 'models/hall-hi.glb', lo: 'models/hall-lo.glb', fit: {}, families: { A: { hi: 'models/hall-hi-A.glb', lo: 'models/hall-lo-A.glb' }, B: { hi: 'models/hall-hi-B.glb' } } }
    expect(scanUrl(src, 'hi', 'A')).toBe('models/hall-hi-A.glb')
    expect(scanUrl(src, 'pi', 'A')).toBe('models/hall-lo-A.glb')
    expect(scanUrl(src, 'pi', 'B')).toBe('models/hall-hi-B.glb') // B has only the detailed file
    expect(scanUrl(src, 'hi', 'C')).toBe('models/hall-hi.glb')
    expect(scanUrl(src, 'hi', null)).toBe('models/hall-hi.glb')
  })
})

describe('?lift', () => {
  it('brightens only when asked, and only within 0.5 to 2', () => {
    expect(hallLift(new URLSearchParams(''))).toBe(1)
    expect(hallLift(new URLSearchParams('lift=1.4'))).toBe(1.4)
    expect(hallLift(new URLSearchParams('lift=5'))).toBe(1)
    expect(hallLift(new URLSearchParams('lift=nope'))).toBe(1)
  })
})

describe('what stands under a point of the model', () => {
  // A floor at -0.03 (two triangles, 4 m square) and a desk top at 0.72 over its northern strip (scene z -1..-0.5).
  const quad = (x0: number, z0: number, x1: number, z1: number, y: number) => [x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z0, x1, y, z1, x0, y, z1]
  const tris = new Float32Array([...quad(-2, -2, 2, 2, -0.03), ...quad(-2, -1, 2, -0.5, 0.72)])

  it('is the desk top over the desk and the floor beside it', () => {
    expect(surfaceUnder(tris, 0, -0.75, 1)).toBeCloseTo(0.72)
    expect(surfaceUnder(tris, 0, 0.5, 1)).toBeCloseTo(-0.03)
  })

  it('is the floor for something lower than the desk top, and nothing outside the model', () => {
    expect(surfaceUnder(tris, 0, -0.75, 0.5)).toBeCloseTo(-0.03)
    expect(surfaceUnder(tris, 5, 0, 1)).toBeNull()
  })

  it('leaves out what the clear box leaves out of the drawing', () => {
    const clear = new Box3(new Vector3(-1, 0, -1.2), new Vector3(1, 1.35, -0.4))
    expect(surfaceUnder(tris, 0, -0.75, 1, clear)).toBeCloseTo(-0.03)
  })
})
