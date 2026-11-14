import { Color, DataTexture, LinearFilter, Mesh, PlaneGeometry, RGFormat, ShaderMaterial, UnsignedByteType } from 'three'
import type { Xray } from './contract'
import type { Mirror } from './mirror'
import { INK, OLIVE } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// The radio X-ray on the floor, drawn from whatever w x h grid arrives (contract sections 5 and 6).
// People (moving_db) are olive contour bands; objects (static_db) are ink hatching. Both ease between states.

const DB_RANGE = 16 // a byte covers 0..16 dB, about 0.06 dB a step

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
  uniform vec3 uOlive;
  uniform vec3 uInk;
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
    return 1.0 - smoothstep(0.5 * w, 1.5 * w, abs(v - level));
  }

  void main() {
    vec2 db = texture2D(uData, vUv).rg * uRange;
    // People: olive contours at 1.5, 3 and 4.5 dB over a light olive fill that deepens with each band.
    float people = 0.12 * above(db.r, 1.5) + 0.12 * above(db.r, 3.0) + 0.12 * above(db.r, 4.5);
    people = max(people, 0.85 * max(contour(db.r, 1.5), max(contour(db.r, 3.0), contour(db.r, 4.5))));
    // Objects: diagonal ink hatching from 1.5 dB, its strokes thickening with the drop.
    float stroke = mix(0.18, 0.5, clamp((db.g - 1.5) / 6.0, 0.0, 1.0));
    float t = fract((vFloor.x - vFloor.y) / 0.05);
    float edge = fwidth((vFloor.x - vFloor.y) / 0.05);
    float hatch = 0.6 * above(db.g, 1.5) * (1.0 - smoothstep(stroke - edge, stroke + edge, t));
    float a = hatch + people * (1.0 - hatch);
    vec3 rgb = mix(uOlive, uInk, hatch / max(a, 1e-4));
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
        uOlive: { value: new Color(OLIVE) },
        uInk: { value: new Color(INK) },
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
  }

  /** `blind` hides the image: when the radio has failed, the picture means nothing. */
  update(x: Xray | null, blind: boolean) {
    this.fadeTo = x && !blind ? 1 : 0
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
    this.bytes = new Uint8Array(n * 2)
    this.shown = new Float32Array(n * 2)
    this.target = new Float32Array(n * 2)
    this.tex?.dispose()
    // RG8: red = people, green = objects. Linear filtering turns the cells into smooth contours.
    this.tex = new DataTexture(this.bytes, x.w, x.h, RGFormat, UnsignedByteType)
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
    const k = 1 - Math.exp(-dt / 120)
    this.fade += (this.fadeTo - this.fade) * k
    if (Math.abs(this.fadeTo - this.fade) < 0.01) this.fade = this.fadeTo
    let busy = this.fade !== this.fadeTo
    const n = this.shown.length / 2
    for (let i = 0; i < n; i++) {
      for (const j of [i, n + i]) {
        const d = this.target[j] - this.shown[j]
        if (Math.abs(d) > 0.02) busy = true
        this.shown[j] += d * k
        // Interleave for RG8: [moving0, static0, moving1, static1, ...]
        this.bytes[2 * i + (j === i ? 0 : 1)] = Math.round(Math.min(1, this.shown[j] / DB_RANGE) * 255)
      }
    }
    if (this.tex) this.tex.needsUpdate = true
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
    <span><svg width="28" height="18" viewBox="0 0 28 18"><rect x="1" y="1" width="26" height="16" rx="6" fill="#4F5E2E" fill-opacity="0.25" stroke="#4F5E2E" stroke-width="2"/></svg>Person</span>
    <span><svg width="28" height="18" viewBox="0 0 28 18"><path d="M2 18L11 0M9 18L18 0M16 18L25 0M23 18L28 8" stroke="#1C1B17" stroke-opacity="0.6" stroke-width="2"/></svg>Object</span>`
  return el
}
