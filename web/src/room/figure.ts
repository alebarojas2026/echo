import {
  CapsuleGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshLambertMaterial,
  SphereGeometry,
  type BufferGeometry,
  type Material,
  type Object3D,
} from 'three'
import { PERSON } from './palette'
import figureUrl from './figures/person-a.glb?url'

// The person figure, behind one small seam so the final rigged figure can replace this prototype without
// touching the room: createFigure() returns { object, setMoving, setHeading, setOpacity, update, dispose }.
// The caller positions `object` on the floor; the figure only poses itself (walk or stand, and turning).
//
// This prototype is style A (smooth clay) from plan/figures: one mesh, no textures, 1.70 m tall with its
// feet at the origin, facing +z. Two shape keys (stepL, stepR) make the walk, so there is no skinning.
// It is lit by the room's figure lights (Presence adds them); everything else in the room is unlit.
// If the file can't load, it draws the old capsule and head instead.

export interface Figure {
  /** Add this to the scene and move it to the person's floor point. */
  readonly object: Object3D
  /** Walk while moving, stand while still. speedMps sets the step rate (an unhurried walk by default). */
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
/** Full walk cycles (two steps) per second at an indoor pace of about 1 m/s. */
const CYCLE_HZ = 0.85

/** Shortest signed turn from angle a to angle b, in radians. */
export function turn(a: number, b: number): number {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a))
}

let shared: Promise<{ geometry: BufferGeometry; keys: [number, number] | null } | null> | null = null

/** Loads the figure file once for every figure. Resolves null if it can't be loaded. */
function loadShared() {
  shared ??= (async () => {
    try {
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js')
      const gltf = await new GLTFLoader().loadAsync(figureUrl)
      let source: Mesh | null = null
      gltf.scene.traverse((o) => {
        if (!source && o instanceof Mesh) source = o
      })
      if (!source) throw new Error('no mesh in the figure file')
      const mesh = source as Mesh
      // The step names live on the loaded mesh (glTF extras.targetNames), not on the geometry.
      const dict = mesh.morphTargetDictionary ?? {}
      const keys: [number, number] | null = dict.stepL !== undefined && dict.stepR !== undefined ? [dict.stepL, dict.stepR] : null
      return { geometry: mesh.geometry as BufferGeometry, keys }
    } catch (err) {
      console.warn('figure: could not load, drawing the capsule instead.', err)
      return null
    }
  })()
  return shared
}

export function createFigure(onReady?: (loaded: boolean) => void): Figure {
  const object = new Group()
  let mats: Material[] = []
  let body: Mesh | null = null
  let depth: Mesh | null = null
  let keys: [number, number] | null = null
  let alpha = 1
  let heading = 0
  let headingTo = 0
  let walk = 0
  let walkTo = 0
  let rate = CYCLE_HZ
  let phase = 0

  const applyOpacity = () => {
    for (const m of mats) (m as MeshBasicMaterial).opacity = body ? alpha : 0.85 * alpha
    // While see-through, a depth-only twin draws first so only the nearest surface takes colour.
    if (depth) depth.visible = alpha < 0.999
  }

  void loadShared().then((file) => {
    if (file) {
      const mat = new MeshLambertMaterial({ color: PERSON, transparent: true })
      body = new Mesh(file.geometry, mat)
      body.updateMorphTargets()
      body.renderOrder = 11
      depth = new Mesh(file.geometry, new MeshBasicMaterial({ colorWrite: false }))
      depth.morphTargetInfluences = body.morphTargetInfluences
      depth.renderOrder = 10
      body.scale.setScalar(FIGURE_SCALE)
      depth.scale.setScalar(FIGURE_SCALE)
      keys = file.keys
      object.add(depth, body)
      mats = [mat]
    } else {
      const b = new Mesh(new CapsuleGeometry(0.12, 0.62, 4, 12))
      b.position.y = 0.43
      const h = new Mesh(new SphereGeometry(0.1, 16, 12))
      h.position.y = 0.98
      mats = [b, h].map((m) => (m.material = new MeshBasicMaterial({ color: PERSON, transparent: true, depthWrite: false })))
      object.add(b, h)
    }
    applyOpacity()
    onReady?.(!!file)
  })

  return {
    object,
    setMoving(moving, speedMps = 1) {
      walkTo = moving ? 1 : 0
      rate = CYCLE_HZ * Math.min(1.6, Math.max(0.5, speedMps))
    },
    setHeading(rad) {
      headingTo = rad
    },
    setOpacity(a) {
      alpha = a
      applyOpacity()
    },
    update(dtMs) {
      const k = 1 - Math.exp(-dtMs / 220)
      const d = turn(heading, headingTo)
      heading = Math.abs(d) < 0.002 ? headingTo : heading + d * (1 - Math.exp(-dtMs / 160))
      object.rotation.y = body ? heading : 0
      // Walk: stand -> stepL -> stand -> stepR, eased in and out so a stop always settles on the standing pose.
      walk += (walkTo - walk) * k
      if (Math.abs(walkTo - walk) < 0.004) walk = walkTo
      if (walk > 0) phase = (phase + (dtMs / 1000) * rate * 2 * Math.PI) % (2 * Math.PI)
      if (body?.morphTargetInfluences && keys) {
        const s = Math.sin(phase)
        body.morphTargetInfluences[keys[0]] = walk * Math.max(0, s)
        body.morphTargetInfluences[keys[1]] = walk * Math.max(0, -s)
      }
      return heading !== headingTo || walk > 0 || walkTo > 0
    },
    dispose() {
      object.removeFromParent()
      for (const m of mats) m.dispose()
    },
  }
}
