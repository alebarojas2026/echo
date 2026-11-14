import { PerspectiveCamera, Scene, Vector3, WebGLRenderer } from 'three'
import { SQUARE_M } from './frame'
import { BG } from './palette'

// Owns the renderer, the camera and the frame loop. Frames are drawn only when something changed
// or an animation is still settling, so an idle room costs nothing on the Pi.

/** A per-frame step. Returns true while it still needs frames. */
export type Animator = (dtMs: number) => boolean

interface Label {
  el: HTMLElement
  at: Vector3
}

// Two qualities. "pi" is what measurements on a Pi 5 at 1080p chose (issue #12): with antialiasing the GPU was
// about 99% busy at 60 fps and the NO DATA screen dipped to 53 fps; without it, about 40% busy and a steady 60.
// The render scale made no difference there, and DPR 2 fell to 16 fps. "hi" is for a laptop's GPU (the demo
// screen is a MacBook): antialiasing, the display's own DPR up to 2, and the detailed hall model.
export type Quality = 'hi' | 'pi'

export interface ViewOptions {
  quality: Quality
  /** Multisampled edges: on for hi, off for pi; ?aa=1 or ?aa=0 decides instead. */
  antialias: boolean
  /** Canvas pixels per CSS pixel: the display's (up to 2) for hi, 1 for pi; ?dpr= (up to 3) decides instead. */
  pixelRatio: number
}

/** ?q=hi or ?q=pi, else pi when the GPU is the Pi 5's (Broadcom V3D), else hi. */
export function qualityFor(params: URLSearchParams, gpu: string): Quality {
  const q = params.get('q')
  if (q === 'hi' || q === 'pi') return q
  return /\bv3d\b/i.test(gpu) ? 'pi' : 'hi'
}

/** The GPU's name as WebGL reports it, or '' when it can't be read. */
export function gpuName(): string {
  if (typeof document === 'undefined') return ''
  try {
    const gl = document.createElement('canvas').getContext('webgl')
    if (!gl) return ''
    const info = gl.getExtension('WEBGL_debug_renderer_info')
    const name = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER))
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return name
  } catch {
    return ''
  }
}

/** Picks the quality, then reads ?aa= and ?dpr= so the screen can be tuned from its URL without a rebuild. */
export function viewOptions(params: URLSearchParams, gpu = gpuName(), deviceRatio = globalThis.devicePixelRatio ?? 1): ViewOptions {
  const quality = qualityFor(params, gpu)
  const hi = quality === 'hi'
  const aa = params.get('aa')
  const dpr = Number(params.get('dpr'))
  return {
    quality,
    antialias: aa === '1' ? true : aa === '0' ? false : hi,
    pixelRatio: dpr > 0 && dpr <= 3 ? dpr : hi ? Math.min(2, Math.max(1, deviceRatio)) : 1,
  }
}

// North straight up the screen, seen from the south and 52 degrees up, so the zones read 1 2 / 3 4 and the
// plinth, the low walls and the 1 m stands read as a scale model. A narrow 20 degree lens keeps the far edge
// nearly as wide as the near one. Framing is for the contract's 2 m square and scales with nodes.json.
const ELEV_DEG = 52
const TARGET_M = new Vector3(0, 0.4, 0.1)
const FIT_RADIUS_M = 1.45
export const FOV_DEG = 20

/** Where the camera looks from: degrees above the floor (seen from the south), what it looks at, and the
 *  radius of the sphere around that point it must fit in view. */
export interface Shot {
  elevDeg: number
  target: Vector3
  radiusM: number
}

/** The room's normal framing, scaled to nodes.json's square. */
export function roomShot(): Shot {
  const scale = SQUARE_M / 2
  return { elevDeg: ELEV_DEG, target: TARGET_M.clone().multiplyScalar(scale), radiusM: FIT_RADIUS_M * scale }
}

/** Straight down on the square, north up: for lining a scan up by eye (align mode). */
export function topShot(): Shot {
  // 89.5 rather than 90 keeps "north up" well defined for lookAt.
  return { elevDeg: 89.5, target: new Vector3(0, 0, 0), radiusM: FIT_RADIUS_M * (SQUARE_M / 2) }
}

/** Points the camera at the shot's target and backs off until its sphere fits the narrower field of view. */
export function fitCamera(camera: PerspectiveCamera, width: number, height: number, shot: Shot = roomShot()) {
  camera.aspect = width / height
  const vfov = (camera.fov * Math.PI) / 180
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect)
  const elev = (shot.elevDeg * Math.PI) / 180
  const dist = shot.radiusM / Math.sin(Math.min(vfov, hfov) / 2)
  camera.position.set(0, Math.sin(elev), Math.cos(elev)).multiplyScalar(dist).add(shot.target)
  camera.lookAt(shot.target)
  // Depth range to suit the distance: about 8 m for the square, about 100 m for the whole hall.
  camera.near = Math.max(0.05, dist / 100)
  camera.far = dist * 3 + 20
  camera.updateProjectionMatrix()
  camera.updateMatrixWorld()
}

export class RoomView {
  readonly renderer: WebGLRenderer
  readonly scene = new Scene()
  readonly camera = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
  readonly labelLayer: HTMLElement
  private readonly labels: Label[] = []
  private readonly animators = new Set<Animator>()
  private readonly resizeHooks: ((w: number, h: number) => void)[] = []
  private width = 1
  private height = 1
  private frame = 0
  private lastFrameAt = 0
  private labelsDirty = true
  private readonly scratch = new Vector3()
  private shot = roomShot()

  constructor(readonly host: HTMLElement, opts: Partial<ViewOptions> = {}) {
    this.renderer = new WebGLRenderer({ antialias: opts.antialias ?? false, powerPreference: 'high-performance' })
    this.renderer.setClearColor(BG, 1)
    this.renderer.setPixelRatio(opts.pixelRatio ?? 1)
    this.renderer.domElement.className = 'room-canvas'
    this.renderer.domElement.setAttribute('aria-hidden', 'true')
    host.append(this.renderer.domElement)

    this.labelLayer = document.createElement('div')
    this.labelLayer.className = 'room-labels'
    this.labelLayer.setAttribute('aria-hidden', 'true')
    host.append(this.labelLayer)

    new ResizeObserver(() => this.resize()).observe(host)
    this.resize()
  }

  /** Adds a text label pinned to a scene point. Returns the element so callers can restyle or move it. */
  addLabel(text: string, at: Vector3, className = ''): HTMLElement {
    const el = document.createElement('span')
    el.className = `room-label ${className}`.trim()
    el.textContent = text
    this.labelLayer.append(el)
    this.labels.push({ el, at: at.clone() })
    this.labelsDirty = true
    return el
  }

  moveLabel(el: HTMLElement, at: Vector3) {
    const label = this.labels.find((l) => l.el === el)
    if (!label || label.at.equals(at)) return
    label.at.copy(at)
    this.labelsDirty = true
    this.requestRender()
  }

  /** Calls fn with the canvas size in CSS pixels now and after every resize. */
  onResize(fn: (w: number, h: number) => void) {
    this.resizeHooks.push(fn)
    fn(this.width, this.height)
  }

  addAnimator(fn: Animator) {
    this.animators.add(fn)
    this.requestRender()
  }

  /** Moves the camera to `shot` (kept across resizes). */
  setShot(shot: Shot) {
    this.shot = shot
    fitCamera(this.camera, this.width, this.height, shot)
    this.labelsDirty = true
    this.requestRender()
  }

  requestRender() {
    if (this.frame) return
    this.frame = requestAnimationFrame((now) => this.draw(now))
  }

  private resize() {
    const w = Math.max(1, this.host.clientWidth)
    const h = Math.max(1, this.host.clientHeight)
    this.width = w
    this.height = h
    this.renderer.setSize(w, h, false)
    fitCamera(this.camera, w, h, this.shot)
    for (const fn of this.resizeHooks) fn(w, h)
    this.labelsDirty = true
    this.requestRender()
  }

  private draw(now: number) {
    this.frame = 0
    const dt = this.lastFrameAt ? Math.min(100, now - this.lastFrameAt) : 16
    this.lastFrameAt = now
    let busy = false
    for (const step of this.animators) busy = step(dt) || busy
    this.renderer.render(this.scene, this.camera)
    if (this.labelsDirty) this.placeLabels()
    if (busy) this.requestRender()
    else this.lastFrameAt = 0
  }

  private placeLabels() {
    this.labelsDirty = false
    this.camera.updateMatrixWorld()
    for (const { el, at } of this.labels) {
      const p = this.scratch.copy(at).project(this.camera)
      const x = ((p.x + 1) / 2) * this.width
      const y = ((1 - p.y) / 2) * this.height
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`
    }
  }
}
