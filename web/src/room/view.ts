import { Box3, PerspectiveCamera, Scene, Vector3, WebGLRenderer } from 'three'
import { FIGURE_HEIGHT_M } from './figure'
import { NODES, SIZE_M, STRIP_M, ZONES, alertWordAt, nodeLabelSide, toScene, type Vec3 } from './frame'
import { BG } from './palette'
import { DESK_TOP_M } from './stage'

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

/** A shot that depends on the canvas size. */
export type ShotFor = (width: number, height: number) => Shot

/**
 * Words that sit beside the layout and need room toward the canvas edge: the names of the nodes on its east
 * and west edges (beside their heads, outward) and each zone's no-movement word (on the floor just outside,
 * outward). "West beacon" and "No movement" at 28 px are about 170 px wide; with their gap and the 24 px edge
 * margin, 200 px.
 */
const SIDE_WORDS_PX = 200
function sideWordAnchors(): Vector3[] {
  const nodes = Object.values(NODES).filter((n) => {
    const side = nodeLabelSide(n.id)
    return (side === 'left' && n.xyz[0] <= 0.05) || (side === 'right' && n.xyz[0] >= SIZE_M[0] - 0.05)
  })
  return [...nodes.map((n) => n.xyz), ...ZONES.map((z) => alertWordAt(z.id)[0])].map((p) => new Vector3(...toScene(p)))
}

/** The layout's framing scale: half its longer side (1 for the 2 m square). */
function layoutScale(): number {
  return Math.max(SIZE_M[0], SIZE_M[1]) / 2
}

/**
 * The room's normal framing. The square's is scaled to nodes.json's size; on a narrow canvas (a laptop, beside
 * the panels' rail) it backs off just enough that the words beside the square stay on the canvas, and on the
 * 1920 x 1080 screen's 1280 x 1080 canvas they already fit, so it doesn't change there. The desk's is fitted to
 * what is on the desk (deskShot).
 */
export function roomShot(width = 1280, height = 1080): Shot {
  if (STRIP_M) return deskShot(width, height)
  const scale = layoutScale()
  const shot = { elevDeg: ELEV_DEG, target: TARGET_M.clone().multiplyScalar(scale), radiusM: FIT_RADIUS_M * scale }
  const room = width / 2 - SIDE_WORDS_PX
  if (room <= 0) return shot
  const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 100)
  const anchors = sideWordAnchors()
  // A point's distance from the middle of the canvas shrinks about in step with the camera's distance, so a
  // few rounds of "back off by how far over we are" settle it.
  for (let round = 0; round < 4; round++) {
    fitCamera(cam, width, height, shot)
    const over = Math.max(...anchors.map((a) => (Math.abs(a.clone().project(cam).x) * width) / 2 / room))
    if (over <= 1) break
    shot.radiusM *= over * 1.005
  }
  return shot
}

// The desk (#415) is framed on what is on it rather than scaled from the square: a little higher up, so a person
// in the strip covers less of the desk behind them, and fitted to the strip, the desk top, a person's head anywhere
// in the strip, the five devices with their names above them and the words in the aisle, then centred on the
// canvas. Every point comes from nodes.json; the pixel sizes are the words' as drawn (room.css).
const DESK_ELEV_DEG = 58
const EDGE_PX = 24
/** Below the layout: the legend's row in the canvas's bottom corner. */
const BOTTOM_PX = 72
const NAME_PX = 28 // room-label--node, and the no-movement word
const LINE_PX = 31
const CHAR_EM = 0.56 // Hanken Grotesk's average letter width at 600
const XRAY_CAPTION_PX = 520

/** A point that must be on the canvas, with the words around it: pixels to its left, right, above and below. */
export interface Anchor {
  at: Vector3
  left: number
  right: number
  up: number
  down: number
}

const wordsPx = (text: string) => text.length * CHAR_EM * NAME_PX

export function deskAnchors(personM = FIGURE_HEIGHT_M): Anchor[] {
  const [sw, sh] = STRIP_M ?? SIZE_M
  const [fw, fh] = SIZE_M
  const out: Anchor[] = []
  const add = (p: Vec3, left = 0, right = 0, up = 0, down = 0) => out.push({ at: new Vector3(...toScene(p)), left, right, up, down })
  for (const p of [[0, 0, 0], [sw, 0, 0], [0, sh, 0], [sw, sh, 0], [0, fh, DESK_TOP_M], [fw, fh, DESK_TOP_M]] as Vec3[]) add(p)
  for (const x of [0.15, sw - 0.15]) for (const y of [0.1, sh - 0.1]) add([x, y, personM])
  // A name sits 12 px above its device's head, centred, or just below it reading inward; two lines when it says
  // "not heard".
  const tall = 12 + 2 * LINE_PX
  for (const n of Object.values(NODES)) {
    const w = wordsPx(n.name)
    const side = nodeLabelSide(n.id)
    if (side === 'below-right') add(n.xyz, 8, w + 10, 8, tall)
    else if (side === 'below-left') add(n.xyz, w + 10, 8, 8, tall)
    else add(n.xyz, w / 2, w / 2, tall, 8)
  }
  for (const z of ZONES) add(alertWordAt(z.id)[0], wordsPx('No movement') / 2, wordsPx('No movement') / 2, 0, LINE_PX)
  add([0, -0.36, 0], 0, XRAY_CAPTION_PX, LINE_PX / 2, LINE_PX / 2) // xray.ts's caption, read from the strip's west end
  return out
}

type AxisItem = [at: number, below: number, above: number]

/** Where values `at`, zoomed by `s`, reach with their words: [lowest, highest]. */
function reach(items: readonly AxisItem[], s: number): [number, number] {
  return [Math.min(...items.map(([u, below]) => s * u - below)), Math.max(...items.map(([u, , above]) => s * u + above))]
}

/** The largest zoom at which the values with their words fit in `span` pixels. */
function fitAxis(items: readonly AxisItem[], span: number): number {
  let lo = 0.01
  let hi = 100
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2
    const [b, t] = reach(items, mid)
    if (t - b <= span) lo = mid
    else hi = mid
  }
  return lo
}

/** The shot at `elevDeg` that shows every anchor with its words, as large as fits, centred in the canvas less
 *  its edges (and the legend's row at the bottom). */
export function fitShot(anchors: readonly Anchor[], width: number, height: number, elevDeg: number): Shot {
  const box = new Box3().setFromPoints(anchors.map((a) => a.at))
  const shot: Shot = { elevDeg, target: box.getCenter(new Vector3()), radiusM: Math.max(0.1, box.getSize(new Vector3()).length() / 2) }
  const cam = new PerspectiveCamera(FOV_DEG, 1, 0.1, 100)
  const p = new Vector3()
  const right = new Vector3()
  const up = new Vector3()
  // The view is nearly orthographic (20 degree lens), so a few rounds of "move by the offset, zoom by the ratio"
  // settle it.
  for (let round = 0; round < 8; round++) {
    fitCamera(cam, width, height, shot)
    const px = anchors.map((a) => {
      p.copy(a.at).project(cam)
      return { x: (p.x * width) / 2, y: (p.y * height) / 2, a }
    })
    const xs = px.map((q): AxisItem => [q.x, q.a.left, q.a.right])
    const ys = px.map((q): AxisItem => [q.y, q.a.down, q.a.up])
    const s = Math.min(fitAxis(xs, width - 2 * EDGE_PX), fitAxis(ys, height - EDGE_PX - BOTTOM_PX))
    // Zoomed by s about the canvas middle, the content's middle moves to the free band's middle (the band sits a
    // little above the canvas's middle, clear of the legend's row): how far that is in today's pixels.
    const [x0, x1] = reach(xs, s)
    const [y0, y1] = reach(ys, s)
    const dx = (x0 + x1) / 2 / s
    const dy = ((y0 + y1) / 2 - (BOTTOM_PX - EDGE_PX) / 2) / s
    const perPx = (2 * cam.position.distanceTo(shot.target) * Math.tan((cam.fov * Math.PI) / 360)) / height
    right.setFromMatrixColumn(cam.matrixWorld, 0)
    up.setFromMatrixColumn(cam.matrixWorld, 1)
    shot.target.addScaledVector(right, dx * perPx).addScaledVector(up, dy * perPx)
    shot.radiusM /= s
    if (Math.abs(s - 1) < 1e-3 && Math.hypot(dx, dy) < 0.5) break
  }
  return shot
}

/** The desk's framing for this canvas. */
export function deskShot(width = 1280, height = 1080): Shot {
  return fitShot(deskAnchors(), width, height, DESK_ELEV_DEG)
}

// Inside the hall model, the desk's close view is in situ: the person at true size at our desk, with the real desk
// run, its chairs and the neighbouring rows around them. Seen from behind the person (up the tiers), north up,
// 45 degrees up. The next row's desk stands 0.75 m high a third of a metre behind the strip; from this angle it
// would hide the strip's floor and the person's legs, so that span is drawn see-through (scan.ts, ghostBox).
// Fitted like the desk's own view (every word on the canvas), but on the 1280 px canvas never tighter than
// SITU_MIN_RADIUS_M, so the rows around stay in view; a narrower canvas keeps the same share of its width for them
// (the words would crowd otherwise).
const SITU_ELEV_DEG = 45
const PERSON_M = 1.7
const SITU_MIN_RADIUS_M = 1.7

/** The close view inside the hall, for the desk layout. */
export function inSituShot(width = 1280, height = 1080): Shot {
  const shot = fitShot(deskAnchors(PERSON_M), width, height, SITU_ELEV_DEG)
  return { ...shot, radiusM: Math.max(shot.radiusM, SITU_MIN_RADIUS_M * Math.min(1, width / 1280)) }
}

/** Straight down on the square, north up: for lining a scan up by eye (align mode). */
export function topShot(): Shot {
  // 89.5 rather than 90 keeps "north up" well defined for lookAt.
  return { elevDeg: 89.5, target: new Vector3(0, 0, 0), radiusM: FIT_RADIUS_M * layoutScale() }
}

/** Points the camera at the shot's target and backs off until its sphere fits the narrower field of view. */
export function fitCamera(camera: PerspectiveCamera, width: number, height: number, shot: Shot = roomShot(width, height)) {
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
  readonly figures = new Scene()
  readonly camera = new PerspectiveCamera(FOV_DEG, 1, 0.1, 60)
  readonly labelLayer: HTMLElement
  readonly wideLayer: HTMLElement
  private readonly labels: Label[] = []
  private readonly animators = new Set<Animator>()
  private readonly resizeHooks: ((w: number, h: number) => void)[] = []
  private width = 1
  private height = 1
  private frame = 0
  private lastFrameAt = 0
  private labelsDirty = true
  private readonly scratch = new Vector3()
  private shot: Shot | ShotFor = roomShot

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
    // Words that belong to the whole hall ("Movement on this path") stay when the camera goes wide and the room's
    // own labels step back.
    this.wideLayer = document.createElement('div')
    this.wideLayer.className = 'room-labels'
    this.wideLayer.setAttribute('aria-hidden', 'true')
    host.append(this.wideLayer)

    new ResizeObserver(() => this.resize()).observe(host)
    this.resize()
  }

  /** Adds a text label pinned to a scene point. Returns the element so callers can restyle or move it. */
  addLabel(text: string, at: Vector3, className = '', wide = false): HTMLElement {
    const el = document.createElement('span')
    el.className = `room-label ${className}`.trim()
    el.textContent = text
    ;(wide ? this.wideLayer : this.labelLayer).append(el)
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

  /** The canvas size in CSS pixels. */
  get size(): [number, number] {
    return [this.width, this.height]
  }

  /** Moves the camera to `shot`, kept across resizes; a ShotFor is asked again at every new size. */
  setShot(shot: Shot | ShotFor) {
    this.shot = shot
    fitCamera(this.camera, this.width, this.height, this.shotNow())
    this.labelsDirty = true
    this.requestRender()
  }

  private shotNow(): Shot {
    return typeof this.shot === 'function' ? this.shot(this.width, this.height) : this.shot
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
    // How big the room is drawn next to the 1280 px canvas it was laid out for; the zone names scale with it.
    this.host.style.setProperty('--room-k', String(Math.min(1, w / 1280)))
    fitCamera(this.camera, w, h, this.shotNow())
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
    if (this.figures.children.some(figure => figure.visible)) {
      // The person stays in front of room strokes, with its own depth buffer for solid shading and fades.
      const autoClear = this.renderer.autoClear
      this.renderer.autoClear = false
      this.renderer.clearDepth()
      this.renderer.render(this.figures, this.camera)
      this.renderer.autoClear = autoClear
    }
    if (this.labelsDirty) this.placeLabels()
    this.declutter()
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

  /** Current posed silhouettes projected to screen bounds, including room for a label's edge. */
  private figureBoxes() {
    const canvas = this.renderer.domElement.getBoundingClientRect()
    const box = new Box3(), point = new Vector3()
    return this.figures.children.filter(figure => figure.visible).flatMap(figure => {
      box.setFromObject(figure, true)
      if (box.isEmpty()) return []
      let left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity
      for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
        point.set(x, y, z).project(this.camera)
        const px = canvas.left + (point.x + 1) * canvas.width / 2
        const py = canvas.top + (1 - point.y) * canvas.height / 2
        left = Math.min(left, px); right = Math.max(right, px)
        top = Math.min(top, py); bottom = Math.max(bottom, py)
      }
      return [{ left: left - 8, top: top - 8, right: right + 8, bottom: bottom + 8 }]
    })
  }

  /** Labels yield to the figure first, then to higher-priority labels. */
  private declutter() {
    const shown = this.labels.filter(({ el }) => !el.hidden && el.textContent)
    const boxes = shown.map(({ el }) => el.getBoundingClientRect())
    const ranks = shown.map(({ el }) => labelRank(el))
    const figures = this.figureBoxes()
    const blocked = new Set(shown.filter((_, i) => figures.some(figure => intersects(boxes[i], figure))).map(({ el }) => el))
    const yielding = new Set(blocked)
    for (let i = 0; i < shown.length; i++) {
      if (blocked.has(shown[i].el)) continue
      for (let j = i + 1; j < shown.length; j++) {
        if (blocked.has(shown[j].el)) continue
        const a = boxes[i]
        const b = boxes[j]
        if (ranks[i] === ranks[j] || !intersects(a, b)) continue
        yielding.add(ranks[i] < ranks[j] ? shown[i].el : shown[j].el)
      }
    }
    for (const { el } of this.labels) el.classList.toggle('room-label--yield', yielding.has(el))
  }
}

/** Which words win when two overlap: what is happening now beats where things are. */
const RANKS: [string, number][] = [
  ['room-label--object', 3],
  ['room-label--alert', 3],
  ['room-label--wave', 3],
  ['room-label--hall', 3],
  ['room-label--spot', 2],
  ['room-label--beam', 2],
  ['room-label--zone', 1],
]

function labelRank(el: HTMLElement): number {
  return Math.max(0, ...RANKS.filter(([cls]) => el.classList.contains(cls)).map(([, rank]) => rank))
}

type ScreenBox = { left: number; top: number; right: number; bottom: number }
function intersects(a: ScreenBox, b: ScreenBox) {
  return a.right > b.left && b.right > a.left && a.bottom > b.top && b.bottom > a.top
}
