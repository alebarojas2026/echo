import { BufferGeometry, Color, Float32BufferAttribute, Matrix4, Vector3 } from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'

// Baked flat shading for the model pieces: each face gets a colour between `dark` and `light` from one
// fixed light up and to the north-west, written into vertex colours. The GPU draws it with MeshBasicMaterial
// (no lights, no shadow maps), so a shaded room costs the Pi 5 what a flat one does.

const LIGHT = new Vector3(-0.45, 1, -0.3).normalize()
const TOP = LIGHT.y // what a face pointing straight up receives

export interface Part {
  geom: BufferGeometry
  light: number
  dark: number
  /** Where the part sits inside the model piece. */
  at?: Matrix4
  /** One tone per facet instead of smooth shading. */
  flat?: boolean
  /** Rounds the shading to this many steps (a toon look on round parts). */
  bands?: number
}

const n = new Vector3()
const c = new Color()
const lo = new Color()
const hi = new Color()

/** One shaded, non-indexed geometry with a `color` attribute, ready for MeshBasicMaterial({ vertexColors: true }). */
export function shadedGeometry(parts: Part[]): BufferGeometry {
  const out: BufferGeometry[] = []
  for (const p of parts) {
    let g = p.geom.clone()
    if (p.at) g.applyMatrix4(p.at)
    if (!g.getAttribute('normal')) g.computeVertexNormals()
    if (g.index) g = g.toNonIndexed()
    if (p.flat) {
      // a non-indexed geometry gets one normal per triangle: every facet is one tone
      g.deleteAttribute('normal')
      g.computeVertexNormals()
    }
    g.deleteAttribute('uv')
    g.deleteAttribute('uv1')
    const normals = g.getAttribute('normal')
    const colors = new Float32Array(normals.count * 3)
    lo.setHex(p.dark)
    hi.setHex(p.light)
    for (let i = 0; i < normals.count; i++) {
      n.fromBufferAttribute(normals, i)
      let k = Math.max(0, n.dot(LIGHT)) / TOP // 1 for an up-facing face
      k = Math.min(1, k)
      if (p.bands) k = Math.round(k * p.bands) / p.bands
      c.copy(lo).lerp(hi, k)
      colors.set([c.r, c.g, c.b], i * 3)
    }
    g.setAttribute('color', new Float32BufferAttribute(colors, 3))
    g.deleteAttribute('normal')
    out.push(g)
  }
  const merged = mergeGeometries(out, false)
  for (const g of out) g.dispose()
  return merged!
}

/** Translate, then turn (y, x, z), then scale: where a part sits inside its model piece. */
export function at(x: number, y: number, z: number, rx = 0, ry = 0, rz = 0, sx = 1, sy = 1, sz = 1): Matrix4 {
  return new Matrix4()
    .makeTranslation(x, y, z)
    .multiply(new Matrix4().makeRotationY(ry))
    .multiply(new Matrix4().makeRotationX(rx))
    .multiply(new Matrix4().makeRotationZ(rz))
    .multiply(new Matrix4().makeScale(sx, sy, sz))
}

/** Mixes two palette colours (0 = a, 1 = b) into one hex, for tones between palette steps. */
export function mix(a: number, b: number, t: number): number {
  return new Color(a).lerp(new Color(b), t).getHex()
}
