import { PerspectiveCamera, Scene, Vector3, WebGLRenderer } from 'three'
import { SQUARE_M } from './frame'
import { PAPER } from './palette'

// Owns the renderer, the camera and the frame loop. Frames are drawn only when something changed
// or an animation is still settling, so an idle room costs nothing on the Pi.

/** A per-frame step. Returns true while it still needs frames. */
export type Animator = (dtMs: number) => boolean

interface Label {
  el: HTMLElement
  at: Vector3
}

// Defaults are set for the Pi 5 kiosk: no multisampling and one canvas pixel per CSS pixel.
export interface ViewOptions {
  /** Multisampled edges. Off by default; ?aa=1 turns it on. */
  antialias?: boolean
  /** Canvas pixels per CSS pixel. 1 by default; ?dpr=2 (any value up to 3) for sharper screens. */
  pixelRatio?: number
}

/** Reads ?aa= and ?dpr= so the screen can be tuned from its URL without a rebuild. */
export function viewOptions(params: URLSearchParams): ViewOptions {
  const dpr = Number(params.get('dpr'))
  return {
    antialias: params.get('aa') === '1',
    pixelRatio: dpr > 0 && dpr <= 3 ? dpr : 1,
  }
}

const VIEW_DIR = new Vector3(0.26, 1.2, 1).normalize()
// Framing for the contract's 2 m square; both scale with the square from nodes.json.
const TARGET_Y_M = 0.25
const FIT_RADIUS_M = 2.0

export class RoomView {
  readonly renderer: WebGLRenderer
  readonly scene = new Scene()
  readonly camera = new PerspectiveCamera(30, 1, 0.1, 40)
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

  constructor(readonly host: HTMLElement, opts: ViewOptions = {}) {
    this.renderer = new WebGLRenderer({ antialias: opts.antialias ?? false, powerPreference: 'high-performance' })
    this.renderer.setClearColor(PAPER, 1)
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
    this.camera.aspect = w / h
    // Fit the room in whichever of the two fields of view is narrower.
    const vfov = (this.camera.fov * Math.PI) / 180
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect)
    const scale = SQUARE_M / 2
    const target = new Vector3(0, TARGET_Y_M * scale, 0)
    const dist = (FIT_RADIUS_M * scale) / Math.sin(Math.min(vfov, hfov) / 2)
    this.camera.position.copy(VIEW_DIR).multiplyScalar(dist).add(target)
    this.camera.lookAt(target)
    this.camera.updateProjectionMatrix()
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
