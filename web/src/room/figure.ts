import {
  AnimationMixer,
  CapsuleGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshMatcapMaterial,
  SkinnedMesh,
  SphereGeometry,
  type AnimationAction,
  type AnimationClip,
  type Object3D,
} from 'three'
import { PERSON } from './palette'
import figureUrl from './assets/person.glb?url'

// The person figure, behind one small seam: createFigure() returns { object, setMoving, setHeading, setOpacity,
// update, dispose }. The caller positions `object` on the floor; the figure only poses itself (walk or stand, and
// turning) and never reads the room state.
//
// assets/person.glb is a smooth, faceless clay adult built by tools/build_figure.py: 1.70 m tall, feet at the
// origin, facing +z, one skinned mesh with soft ambient occlusion in its vertex colours, 19 bones and two clips.
// "walk" is an in-place loop whose planted foot moves back at exactly the file's walkSpeedMps, so the feet hold
// still on the floor when the figure travels at that speed. "idle" is a calm standing loop: a breath every 4 s and
// one slow weight shift. The idle runs on the wall clock, so it needs no frames of its own: whenever the room
// draws (the feed asks for a frame on every update), the figure shows the idle pose for that moment.
//
// Shading is self-contained: one shared material, lit from the camera's upper left in view space, so the figure
// looks the same wherever it stands and needs no scene lights. Everything else in the room stays unlit.

export interface Figure {
  /** Add this to the scene and move it to the person's floor point. */
  readonly object: Object3D
  /**
   * Walk while moving, stand while still. With speedMps (how fast the floor point travels, in scene metres per
   * second) the stride and step rate follow the speed so the feet don't slide; without it the figure walks at its
   * natural pace (a 1.07 s cycle).
   */
  setMoving(moving: boolean, speedMps?: number): void
  /** Which way to face, in radians about the vertical: 0 faces the camera (+z). The figure turns smoothly. */
  setHeading(rad: number): void
  /** 0..1. Below 1 the figure draws see-through, nearest surface only. */
  setOpacity(alpha: number): void
  /** Advance the pose by dtMs milliseconds. Returns true while it still needs frames. */
  update(dtMs: number): boolean
  dispose(): void
}

/** Drawn 1.22 m tall: about 200 px on the kiosk, clear of the zone names. */
export const FIGURE_SCALE = 0.72
/** The top of the figure's head above the floor, in metres, as drawn. */
export const FIGURE_HEIGHT_M = 1.7 * FIGURE_SCALE
/** Walk and idle swap over this long. */
export const CROSSFADE_MS = 300
/** The full-size walk's speed if the file doesn't carry it (it does: scene extras walkSpeedMps). */
export const WALK_SPEED_MPS = 1.10625

const TURN_MS = 160 // heading time constant
const RATE_MS = 250 // step-rate time constant, so a jumpy speed doesn't jerk the cadence
const MIN_STRIDE = 0.5
const MIN_RATE = 0.55
const MAX_RATE = 1.6

/** Shortest signed turn from angle a to angle b, in radians. */
export function turn(a: number, b: number): number {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a))
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/**
 * How to play the walk for a floor speed: `stride` is how much of the full step to take (the walk's blend weight
 * against the standing pose) and `rate` the playback speed. People slow down by shortening their steps and their
 * cadence about equally, so both follow the square root of the speed ratio, and stride x rate = speed / natural,
 * which keeps the planted foot still. Very slow or very fast speeds clamp (and then the feet slide a little).
 */
export function gait(speedMps: number | undefined, naturalMps: number): { stride: number; rate: number } {
  if (speedMps === undefined || !Number.isFinite(speedMps)) return { stride: 1, rate: 1 }
  const ratio = Math.max(0, speedMps) / naturalMps
  const stride = clamp(Math.sqrt(ratio), MIN_STRIDE, 1)
  return { stride, rate: clamp(ratio / stride, MIN_RATE, MAX_RATE) }
}

/**
 * The figure's pose state with no three.js in it: the walk's blend weight (the idle takes the rest), the walk's
 * playback rate and the heading, and whether any of them is still on its way.
 */
export class FigureMotion {
  moving = false
  speed: number | undefined
  walk = 0
  rate = 1
  heading = 0
  headingTo = 0

  /** naturalMps: the walk's own speed as drawn (the file's speed times the figure's scale). */
  constructor(public naturalMps: number) {}

  target() {
    const g = gait(this.speed, this.naturalMps)
    return { walk: this.moving ? g.stride : 0, rate: g.rate }
  }

  /** Advances by dtMs. Returns true while anything is still changing (walking counts as changing). */
  step(dtMs: number): boolean {
    const t = this.target()
    // A linear crossfade, CROSSFADE_MS from one end to the other; it can turn back midway.
    const fade = dtMs / CROSSFADE_MS
    this.walk = Math.abs(t.walk - this.walk) <= fade ? t.walk : this.walk + Math.sign(t.walk - this.walk) * fade
    this.rate += (t.rate - this.rate) * (1 - Math.exp(-dtMs / RATE_MS))
    if (Math.abs(t.rate - this.rate) < 0.002) this.rate = t.rate
    const d = turn(this.heading, this.headingTo)
    this.heading = Math.abs(d) < 0.002 ? this.headingTo : this.heading + d * (1 - Math.exp(-dtMs / TURN_MS))
    return this.moving || this.walk > 0 || this.heading !== this.headingTo
  }
}

// The clay shade: replaces the matcap material's built-in fallback gradient, so there is no texture at all.
// `normal` is the view-space normal. One soft key light from the upper left: surfaces that face it take exactly the
// person colour, and the far side falls off smoothly to a third of it, so the figure reads as a solid form in the
// room's flat look. The ambient occlusion in the vertex colours darkens the creases.
const SHADE_FROM = 'vec4 matcapColor = vec4( vec3( mix( 0.2, 0.8, uv.y ) ), 1.0 );'
const shadeTo = (darkest: number) => `
  float key = dot( normal, normalize( vec3( -0.6, 0.6, 0.5 ) ) );
  float shade = mix( ${darkest.toFixed(2)}, 1.0, clamp( ( key + 0.45 ) / 1.35, 0.0, 1.0 ) );
  vec4 matcapColor = vec4( vec3( shade ), 1.0 ); // figure-shade`
/** The solid figure's far side, as a fraction of the person colour. */
const DARKEST = 0.3
/** A see-through figure keeps its form but stays light, so it still reads blue over the dark floor. */
const DARKEST_SEE_THROUGH = 0.72

/** Patches a matcap material's fragment shader with the clay shade. Exported for the test. */
export function clayShader(shader: { fragmentShader: string }, darkest = DARKEST): boolean {
  if (!shader.fragmentShader.includes(SHADE_FROM)) {
    console.warn('figure: the matcap shader changed; using its default shade.')
    return false
  }
  shader.fragmentShader = shader.fragmentShader.replace(SHADE_FROM, shadeTo(darkest))
  return true
}

/** The clay material. The see-through one is its own material (clone() would drop the shader patch). */
function clayMaterial(seeThrough: boolean): MeshMatcapMaterial {
  const darkest = seeThrough ? DARKEST_SEE_THROUGH : DARKEST
  const mat = new MeshMatcapMaterial({ color: PERSON, vertexColors: true, transparent: seeThrough })
  mat.onBeforeCompile = (shader) => void clayShader(shader, darkest)
  mat.customProgramCacheKey = () => `figure-clay-${darkest}`
  return mat
}

// The see-through figure's depth pre-pass. It belongs to the transparent pass, after every opaque surface (the
// floor included) and just before its own body: drawn in the opaque pass it would hide the floor behind the figure
// and leave a dark silhouette. The offset keeps the body's own nearest surface from failing the depth test.
const depthMaterial = new MeshBasicMaterial({
  colorWrite: false,
  transparent: true,
  depthWrite: true,
  polygonOffset: true,
  polygonOffsetFactor: 1,
  polygonOffsetUnits: 1,
})
/** Draw order: after the room's floor tiles, heat and alert fill (all at or below 0). */
const DEPTH_ORDER = 10
const BODY_ORDER = 11

interface Source {
  scene: Object3D
  clips: AnimationClip[]
  walkSpeedMps: number
}

let shared: Promise<Source | null> | null = null
let solidMaterial: MeshMatcapMaterial | null = null
let figureCount = 0

/** Loads the figure file once for every figure. Resolves null if it can't be loaded. */
function loadShared(): Promise<Source | null> {
  shared ??= (async () => {
    try {
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js')
      const gltf = await new GLTFLoader().loadAsync(figureUrl)
      const speed = Number(gltf.scene.userData.walkSpeedMps)
      return { scene: gltf.scene, clips: gltf.animations, walkSpeedMps: speed > 0 ? speed : WALK_SPEED_MPS }
    } catch (err) {
      console.warn('figure: could not load, drawing the capsule instead.', err)
      return null
    }
  })()
  return shared
}

export function createFigure(onReady?: (loaded: boolean) => void): Figure {
  const object = new Group()
  const motion = new FigureMotion(WALK_SPEED_MPS * FIGURE_SCALE)
  const idleOffsetS = (figureCount++ * 2.9) % 8 // two figures (a two-zone guess) don't breathe in step
  let disposed = false
  let alpha = 1
  let mixer: AnimationMixer | null = null
  let walk: AnimationAction | null = null
  let idle: AnimationAction | null = null
  let body: SkinnedMesh | null = null
  let twin: SkinnedMesh | null = null
  let seeThrough: MeshMatcapMaterial | null = null
  let fallback: MeshBasicMaterial[] = []

  const applyOpacity = () => {
    if (body && twin && solidMaterial) {
      if (alpha >= 0.999) {
        body.material = solidMaterial
      } else {
        seeThrough ??= clayMaterial(true)
        seeThrough.opacity = alpha
        body.material = seeThrough
      }
      // While see-through, a depth-only twin draws first so only the nearest surface takes colour.
      twin.visible = alpha < 0.999
    }
    for (const m of fallback) m.opacity = alpha
  }

  /** Puts the mixer's weights, rate and idle time in step with `motion`, then poses the skeleton. */
  const pose = (dtMs: number) => {
    if (!mixer || !walk || !idle) return
    walk.setEffectiveWeight(motion.walk)
    walk.setEffectiveTimeScale(motion.rate)
    idle.setEffectiveWeight(1 - motion.walk)
    const d = idle.getClip().duration
    idle.time = (performance.now() / 1000 + idleOffsetS) % d
    mixer.update(motion.walk > 0 ? dtMs / 1000 : 0)
  }

  /** Builds this figure's own copy of the model. Throws if the file isn't the figure it should be. */
  const attach = async (file: Source) => {
    const { clone } = await import('three/addons/utils/SkeletonUtils.js')
    const model = clone(file.scene)
    model.scale.setScalar(FIGURE_SCALE)
    let found: SkinnedMesh | undefined
    model.traverse((o) => {
      if (!found && o instanceof SkinnedMesh) found = o
    })
    const walkClip = file.clips.find((c) => c.name === 'walk')
    const idleClip = file.clips.find((c) => c.name === 'idle')
    if (!found || !walkClip || !idleClip) throw new Error('the file needs a skinned mesh and walk and idle clips')
    const mesh = found as SkinnedMesh
    solidMaterial ??= clayMaterial(false)
    mesh.material = solidMaterial
    mesh.renderOrder = BODY_ORDER
    mesh.frustumCulled = false // the skinned pose reaches past the rest pose's bounds
    const depth = new SkinnedMesh(mesh.geometry, depthMaterial)
    depth.bind(mesh.skeleton, mesh.bindMatrix)
    depth.position.copy(mesh.position)
    depth.quaternion.copy(mesh.quaternion)
    depth.scale.copy(mesh.scale)
    depth.renderOrder = DEPTH_ORDER
    depth.frustumCulled = false
    depth.visible = false
    mesh.parent!.add(depth)
    mixer = new AnimationMixer(model)
    walk = mixer.clipAction(walkClip)
    idle = mixer.clipAction(idleClip)
    idle.setEffectiveTimeScale(0) // the idle follows the clock (see pose), not the mixer
    walk.play()
    idle.play()
    motion.naturalMps = file.walkSpeedMps * FIGURE_SCALE
    body = mesh
    twin = depth
    pose(0)
    object.add(model)
  }

  const useCapsule = () => {
    const b = new Mesh(new CapsuleGeometry(0.12, 0.62, 4, 12))
    b.position.y = 0.43
    const h = new Mesh(new SphereGeometry(0.1, 16, 12))
    h.position.y = 0.98
    fallback = [b, h].map((m) => (m.material = new MeshBasicMaterial({ color: PERSON, transparent: true, depthWrite: false })))
    object.add(b, h)
  }

  void loadShared().then(async (file) => {
    let loaded = false
    if (file && !disposed) {
      try {
        await attach(file)
        loaded = true
      } catch (err) {
        console.warn('figure: could not use the figure file, drawing the capsule instead.', err)
      }
    }
    if (disposed) return
    if (!loaded) useCapsule()
    applyOpacity()
    onReady?.(loaded)
  })

  return {
    object,
    setMoving(moving, speedMps) {
      if (moving && !motion.moving && motion.walk === 0 && walk) {
        // Start the stride so the crossfade's middle lands on mid-stance, where the legs are closest together.
        walk.time = 0.16 * walk.getClip().duration
      }
      motion.moving = moving
      motion.speed = speedMps
    },
    setHeading(rad) {
      motion.headingTo = rad
    },
    setOpacity(a) {
      alpha = clamp(a, 0, 1)
      applyOpacity()
    },
    update(dtMs) {
      const busy = motion.step(dtMs)
      object.rotation.y = mixer || fallback.length ? motion.heading : 0
      pose(dtMs)
      return busy
    },
    dispose() {
      disposed = true
      object.removeFromParent()
      if (mixer) {
        mixer.stopAllAction()
        mixer.uncacheRoot(mixer.getRoot())
      }
      seeThrough?.dispose()
      for (const m of fallback) m.dispose()
    },
  }
}
