import { Color, DataTexture, LinearFilter, Mesh, PlaneGeometry, RGFormat, ShaderMaterial, UnsignedByteType } from 'three'
import type { Xray } from './contract'
import type { Mirror } from './mirror'
import { OBJECT, PERSON, PERSON_HOT } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// The radio X-ray on the floor, drawn from whatever w x h grid arrives (contract sections 5 and 6).
// People (moving_db) are an amber heat-scale shadow; objects (static_db) are grey-blue hatching. Both ease between states.

const DB_RANGE = 16 // a byte covers 0..16 dB, about 0.06 dB a step

const UP = 4 // texture texels per grid cell, each way

/** Catmull-Rom upsampling of a w x h grid (row by row from the south-west) by `f`, never below 0. */
export function upsample(src: ArrayLike<number>, w: number, h: number, f: number): Float32Array {
  const out = new Float32Array(w * f * h * f)
  const at = (ix: number, iy: number) => src[Math.min(h - 1, Math.max(0, iy)) * w + Math.min(w - 1, Math.max(0, ix))]
  const wts = (t: number) => [
    ((-t + 2) * t - 1) * t * 0.5,
    ((3 * t - 5) * t * t + 2) * 0.5,
    ((-3 * t + 4) * t + 1) * t * 0.5,
    (t - 1) * t * t * 0.5,
  ]
  for (let oy = 0; oy < h * f; oy++) {
    const sy = (oy + 0.5) / f - 0.5 // in source cells, 0 = the first cell's centre
    const y0 = Math.floor(sy)
    const wy = wts(sy - y0)
    for (let ox = 0; ox < w * f; ox++) {
      const sx = (ox + 0.5) / f - 0.5
      const x0 = Math.floor(sx)
      const wx = wts(sx - x0)
      let v = 0
      for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) v += wy[j] * wx[i] * at(x0 - 1 + i, y0 - 1 + j)
      out[oy * w * f + ox] = Math.max(0, v)
    }
  }
  return out
}

/** Where the person's shadow is: the centre of the strongest people cells (at least 60% of the peak,
 *  which must reach 1 dB), in contract metres. Null with no clear shadow. */
export function shadowCentre(x: Xray | null): [number, number] | null {
  if (!x || !x.w || !x.h) return null
  const m = x.moving_db
  let max = 0
  for (let i = 0; i < x.w * x.h; i++) max = Math.max(max, m[i] ?? 0)
  if (max < 1) return null
  let sx = 0
  let sy = 0
  let sw = 0
  for (let i = 0; i < x.w * x.h; i++) {
    const v = m[i] ?? 0
    if (v < 0.6 * max) continue
    sx += v * (x.origin_m[0] + ((i % x.w) + 0.5) * x.cell_m)
    sy += v * (x.origin_m[1] + (Math.floor(i / x.w) + 0.5) * x.cell_m)
    sw += v
  }
  return [sx / sw, sy / sw]
}

export interface XrayPeak {
  db: number
  xy: [number, number]
  layer: 'moving' | 'static'
}

/** The strongest cell of either layer, with its centre in contract metres. Null when the grid is empty or flat. */
export function xrayPeak(x: Xray): XrayPeak | null {
  let best: XrayPeak | null = null
  const n = x.w * x.h
  for (let i = 0; i < n; i++) {
    for (const layer of ['moving', 'static'] as const) {
      const db = (layer === 'moving' ? x.moving_db : x.static_db)[i] ?? 0
      if (db > 0 && (!best || db > best.db)) {
        const xy: [number, number] = [x.origin_m[0] + ((i % x.w) + 0.5) * x.cell_m, x.origin_m[1] + (Math.floor(i / x.w) + 0.5) * x.cell_m]
        best = { db, xy, layer }
      }
    }
  }
  return best
}

const vertexShader = /* glsl */ `
  varying vec2 vUv;
  varying vec2 vFloor;
  void main() {
    vUv = uv;
    vec4 world = modelMatrix * vec4(position, 1.0);
    vFloor = world.xz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`

const fragmentShader = /* glsl */ `
  uniform sampler2D uData;
  uniform vec3 uPerson;
  uniform vec3 uPersonHot;
  uniform vec3 uObject;
  uniform float uRange;
  uniform float uFade;
  varying vec2 vUv;
  varying vec2 vFloor;

  float above(float v, float edge) {
    float w = max(fwidth(v), 1e-3);
    return smoothstep(edge - w, edge + w, v);
  }

  float contour(float v, float level) {
    float w = max(fwidth(v), 1e-3);
    return 1.0 - smoothstep(0.7 * w, 1.3 * w, abs(v - level)); // about 2 px wide
  }

  void main() {
    vec2 db = texture2D(uData, vUv).rg * uRange;
    // People: a heat-scale shadow, amber deepening to pale gold at the strongest drop, edged by one
    // 2 px line at 3 dB.
    float edgeLine = 0.9 * contour(db.r, 3.0);
    float people = max(0.7 * smoothstep(1.0, 6.0, db.r), edgeLine);
    vec3 heat = mix(uPerson, uPersonHot, smoothstep(3.0, 8.0, db.r) * (1.0 - edgeLine));
    // Objects: diagonal grey-blue hatching from 1.5 dB, its strokes thickening with the drop.
    float stroke = mix(0.18, 0.5, clamp((db.g - 1.5) / 6.0, 0.0, 1.0));
    float t = fract((vFloor.x - vFloor.y) / 0.05);
    float edge = fwidth((vFloor.x - vFloor.y) / 0.05);
    float hatch = 0.6 * above(db.g, 1.5) * (1.0 - smoothstep(stroke - edge, stroke + edge, t));
    float a = hatch + people * (1.0 - hatch);
    vec3 rgb = mix(heat, uObject, hatch / max(a, 1e-4));
    gl_FragColor = vec4(rgb, a * uFade);
    #include <colorspace_fragment>
  }
`

export class XrayLayer {
  private readonly mesh: Mesh<PlaneGeometry, ShaderMaterial>
  private tex: DataTexture | null = null
  private bytes = new Uint8Array(0)
  private shown = new Float32Array(0) // eased dB, moving then static
  private target = new Float32Array(0)
  private dims = ''
  private w = 0
  private h = 0
  private readonly caption: HTMLElement
  private fade = 0
  private fadeTo = 0

  constructor(private readonly view: RoomView, private readonly mirror: Mirror) {
    const material = new ShaderMaterial({
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uData: { value: null },
        uPerson: { value: new Color(PERSON) },
        uPersonHot: { value: new Color(PERSON_HOT) },
        uObject: { value: new Color(OBJECT) },
        uRange: { value: DB_RANGE },
        uFade: { value: 0 },
      },
    })
    this.mesh = new Mesh(new PlaneGeometry(1, 1), material)
    this.mesh.rotation.x = -Math.PI / 2
    this.mesh.visible = false
    this.mesh.renderOrder = -1
    view.scene.add(this.mesh)
    view.addAnimator((dt) => this.ease(dt))
    this.mirror.set('xray', { 'max-db': null, 'max-xy': null, 'max-layer': null }, 'no radio image')
    view.host.append(legend())
    // On the floor, just south-west of the square, under the router spot tags.
    this.caption = view.addLabel('Radio X-ray: where the links are dimmed', v3([0, -0.36, 0]), 'room-label--xray')
    this.caption.hidden = true
  }

  /** `blind` hides the image: when the radio has failed, the picture means nothing. */
  update(x: Xray | null, blind: boolean) {
    this.fadeTo = x && !blind ? 1 : 0
    this.caption.hidden = !x
    if (x && x.w > 0 && x.h > 0) {
      this.fit(x)
      const n = x.w * x.h
      for (let i = 0; i < n; i++) {
        this.target[i] = Math.max(0, x.moving_db[i] ?? 0)
        this.target[n + i] = Math.max(0, x.static_db[i] ?? 0)
      }
    }
    const peak = x && !blind ? xrayPeak(x) : null
    this.mirror.set(
      'xray',
      peak
        ? { 'max-db': peak.db.toFixed(1), 'max-xy': `${peak.xy[0].toFixed(2)},${peak.xy[1].toFixed(2)}`, 'max-layer': peak.layer }
        : { 'max-db': null, 'max-xy': null, 'max-layer': null },
      peak ? `radio image: strongest ${peak.layer === 'moving' ? 'person' : 'object'} shadow ${peak.db.toFixed(1)} dB at ${peak.xy[0].toFixed(2)}, ${peak.xy[1].toFixed(2)} m` : 'no radio image',
    )
    this.view.requestRender()
  }

  /** Sizes the plane and texture to the grid. A new w x h starts from the new values. */
  private fit(x: Xray) {
    const dims = `${x.w}x${x.h}x${x.cell_m}x${x.origin_m}`
    if (dims === this.dims) return
    this.dims = dims
    const n = x.w * x.h
    this.w = x.w
    this.h = x.h
    this.bytes = new Uint8Array(n * UP * UP * 2)
    this.shown = new Float32Array(n * 2)
    this.target = new Float32Array(n * 2)
    this.tex?.dispose()
    // RG8: red = people, green = objects, UP times finer than the grid so no cell corners show.
    this.tex = new DataTexture(this.bytes, x.w * UP, x.h * UP, RGFormat, UnsignedByteType)
    this.tex.unpackAlignment = 1 // rows of 2*w bytes need not be a multiple of 4
    this.tex.magFilter = LinearFilter
    this.tex.minFilter = LinearFilter
    this.tex.needsUpdate = true
    this.mesh.material.uniforms.uData.value = this.tex
    const sizeX = x.w * x.cell_m
    const sizeY = x.h * x.cell_m
    this.mesh.scale.set(sizeX, sizeY, 1)
    this.mesh.position.copy(v3([x.origin_m[0] + sizeX / 2, x.origin_m[1] + sizeY / 2, 0.002]))
  }

  private ease(dt: number): boolean {
    const k = 1 - Math.exp(-dt / 300) // noisy 10 Hz data: slow enough to hide the noise
    this.fade += (this.fadeTo - this.fade) * k
    if (Math.abs(this.fadeTo - this.fade) < 0.01) this.fade = this.fadeTo
    let busy = this.fade !== this.fadeTo
    const n = this.shown.length / 2
    let moved = false
    for (let j = 0; j < 2 * n; j++) {
      const d = this.target[j] - this.shown[j]
      if (Math.abs(d) > 0.02) busy = true
      if (d !== 0) moved = true
      this.shown[j] += d * k
    }
    if (moved && this.tex) {
      const people = upsample(this.shown.subarray(0, n), this.w, this.h, UP)
      const things = upsample(this.shown.subarray(n), this.w, this.h, UP)
      // Interleave for RG8: [people0, objects0, people1, objects1, ...]
      for (let i = 0; i < people.length; i++) {
        this.bytes[2 * i] = Math.round(Math.min(1, people[i] / DB_RANGE) * 255)
        this.bytes[2 * i + 1] = Math.round(Math.min(1, things[i] / DB_RANGE) * 255)
      }
      this.tex.needsUpdate = true
    }
    this.mesh.material.uniforms.uFade.value = this.fade
    this.mesh.visible = this.fade > 0 && !!this.tex
    return busy
  }
}

/** A small key for the two kinds of shadow. Swatches are inline SVG in the room's colours. */
function legend(): HTMLElement {
  const el = document.createElement('div')
  el.className = 'room-legend'
  el.setAttribute('aria-hidden', 'true')
  el.innerHTML = `
    <span><svg class="room-swatch room-swatch--person" width="28" height="18" viewBox="0 0 28 18"><rect x="1" y="1" width="26" height="16" rx="6" fill="currentColor" fill-opacity="0.45" stroke="currentColor" stroke-width="2"/></svg>Person</span>
    <span><svg class="room-swatch room-swatch--object" width="28" height="18" viewBox="0 0 28 18"><path d="M2 18L11 0M9 18L18 0M16 18L25 0M23 18L28 8" stroke="currentColor" stroke-opacity="0.8" stroke-width="2"/></svg>Object</span>`
  return el
}
