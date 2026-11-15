import { Box3, Color, Group, Mesh, ShaderMaterial, Texture, Vector3, type Object3D } from 'three'
import { NODES, deskEdge, floorSize, toScene } from './frame'
import { FLOOR, WALL_SHADE } from './palette'
import type { Quality, RoomView } from './view'

// The scanned hall, instead of the drawn walls: web/public/models/hall-hi.glb (for a laptop's GPU) or
// hall-lo.glb (for the Pi), with room.glb (npm run scan:prep) as the fallback. A model with vertex colours
// (COLOR_0, its shading baked in) is drawn in those colours; one without is drawn flat in the room's colours.
// vite.config.ts sets __ROOM_SCAN__ at build time only when a file exists, so a board without a scan
// never asks for it. ?scan=0 keeps the drawn room. Alignment comes from web/public/models/room.json, made by
// lining the scan up by eye with ?align=1 (align.ts). Under `vite` the screen asks the dev server instead
// (/__room-scan), so a new scan or alignment shows on reload without a restart.

/** A loaded scan that can be moved: align mode calls `apply` on every key. */
export interface Scan {
  /** The alignment shown now. */
  fit: ScanFit
  apply(fit: ScanFit): void
  /** The scan's box in the scene, as placed now. */
  bounds(): Box3
  /** The cutaway in front of the strip (ghostBox): 0 solid, 1 fully see-through. */
  ghost(amount: number): void
  /** The height (scene y) of the model's highest surface at or below `top` under the scene point (x, z): a desk
   *  top, a chair, the floor. Null when the model has nothing there. What the clear box leaves out doesn't count. */
  under(x: number, z: number, top: number): number | null
  /** The model's own box, in its own metres, before any alignment. */
  box: { min: number[]; max: number[] }
  /** The desk it stands at only because nothing was saved yet (desks.ts), named for the operator; else unset. */
  defaultDesk?: string
}

export type ScanSource = {
  hi?: string
  lo?: string
  fit: ScanFit
  /** Other looks of the same hall to compare (hall-hi-A.glb, ...), picked with ?hall=A. */
  families?: Record<string, { hi?: string; lo?: string }>
} | null

/** The model for this quality: hi takes the detailed one when there is one, pi the light one. With `family`
 *  (?hall=A) that look's files, when it has them. */
export function scanUrl(source: NonNullable<ScanSource>, quality: Quality, family?: string | null): string | undefined {
  const files = (family && source.families?.[family]) || source
  return quality === 'hi' ? (files.hi ?? files.lo) : (files.lo ?? files.hi)
}

/** Where the scan and its alignment are: the dev server's current answer, or what the build found with the
 *  alignment saved on the board (GET /layout, #532) taking over from the build's room.json once there is one. */
async function scanSource(): Promise<ScanSource> {
  if (!import.meta.env.DEV) {
    const built = __ROOM_SCAN__
    if (!built) return null
    try {
      const res = await fetch('/layout', { cache: 'no-store', signal: AbortSignal.timeout(2000) })
      const room = res.ok ? ((await res.json()) as { room?: ScanFit | null }).room : null
      if (room) return { ...built, fit: room }
    } catch {
      // not served by the board, or it has nothing saved: the build's alignment
    }
    return built
  }
  try {
    const res = await fetch('/__room-scan', { cache: 'no-store' })
    if (res.ok) return (await res.json()) as ScanSource
  } catch {
    // not served by vite after all: fall back to the build's answer
  }
  return __ROOM_SCAN__
}

export interface ScanFit {
  /** Move after centring the scan on the square, in contract metres: [east, north]. */
  offset_m?: [number, number]
  /** Turn about the vertical in degrees, counter-clockwise seen from above. */
  yaw_deg?: number
  scale?: number
  /** Anything higher than this (metres) is cut away so the camera sees into the room. */
  cut_m?: number
  /** How far the model's floor sits below ours, in metres: a tier's height when the square stands on that tier. */
  floor_m?: number
}

/** Anything above 1.4 m is cut away unless room.json says otherwise. */
export const DEFAULT_CUT_M = 1.4

export interface Placement {
  /** Moves the scan so its floor centre sits at the origin, on the floor. */
  inner: [number, number, number]
  outer: [number, number, number]
  yaw: number
  scale: number
  cut: number
}

/** Where to put a scan with this bounding box (in its own metres, y up) so it sits on the square. */
export function placeScan(min: [number, number, number], max: [number, number, number], fit: ScanFit = {}): Placement {
  const [dx, dy] = fit.offset_m ?? [0, 0]
  const scale = fit.scale && fit.scale > 0 ? fit.scale : 1
  return {
    inner: [-(min[0] + max[0]) / 2, -min[1], -(min[2] + max[2]) / 2],
    // 3 cm under our floor marks, so a bumpy scanned floor never pokes through them; floor_m lower on a tier.
    outer: [dx, -0.03 - (fit.floor_m ?? 0), -dy],
    yaw: ((fit.yaw_deg ?? 0) * Math.PI) / 180,
    scale,
    cut: fit.cut_m ?? DEFAULT_CUT_M,
  }
}

/** The room-space box kept clear of the model: anything of it standing in the floor a person walks (the hall's
 *  chairs behind our desk) is left out, so the person never stands inside furniture. The floor area from
 *  nodes.json, a little wider east and west and toward the aisle, from just above the floor to above head
 *  height; it stops 1 cm short of where the desk begins (the floor's north edge, or past it when the spot stops
 *  short of the desk). Toward the aisle it stops short of a device that stands across the spot: that device is on
 *  furniture (the desk of the row behind), and the furniture it stands on must stay. */
export function clearBox(): Box3 {
  const [fw, fh] = floorSize()
  const across = Object.values(NODES).map((n) => n.xyz[1]).filter((y) => y < -0.01)
  const back = across.length ? Math.min(CLEAR_BACK_M, Math.max(0, -Math.max(...across) - CLEAR_KEEP_M)) : CLEAR_BACK_M
  const a = new Vector3(...toScene([-CLEAR_SIDE_M, (deskEdge() ?? fh) - 0.01, CLEAR_FLOOR_M]))
  const b = new Vector3(...toScene([fw + CLEAR_SIDE_M, -back, CLEAR_TOP_M]))
  return new Box3().setFromPoints([a, b])
}
/** The clear box stops this far short of a device across the spot (its cube, and the edge it sits on). */
const CLEAR_KEEP_M = 0.08
const CLEAR_SIDE_M = 0.3
const CLEAR_BACK_M = 0.3
const CLEAR_FLOOR_M = 0.0 // the model's floor is 3 cm lower (placeScan), so it stays
const CLEAR_TOP_M = 1.35

/**
 * The span of the model between the close view's camera and the strip: on the desk, the next row's desk run and
 * its chairs, just behind the person. In the close view it is drawn see-through (a cutaway), so the strip's
 * floor and the person's legs show through it. South of the floor area from 1 cm off its edge back to just short
 * of the row after; GHOST_SIDE_M past the floor's east and west ends, where it fades back to solid over
 * GHOST_FADE_M. Above the floor only.
 */
export function ghostBox(): Box3 {
  const [fw] = floorSize()
  const a = new Vector3(...toScene([-GHOST_SIDE_M, -0.005, CLEAR_FLOOR_M]))
  const b = new Vector3(...toScene([fw + GHOST_SIDE_M, -GHOST_BACK_M, GHOST_TOP_M]))
  return new Box3().setFromPoints([a, b])
}
const GHOST_SIDE_M = 1.5
const GHOST_FADE_M = 0.6
const GHOST_BACK_M = 1.75
const GHOST_TOP_M = 2.0
/** How much of a fully see-through surface still shows. */
const GHOST_ALPHA = 0.12

/** Uniforms every material of one scan shares, so the cut, the lift and the cutaway change them all at once. */
interface Shared {
  cut: { value: number }
  lift: { value: number }
  clear: Box3
  ghost: Box3
  /** 0 solid, 1 the cutaway fully see-through. */
  ghostOn: { value: number }
}

/**
 * With `colored`, the model's own vertex colours (shading baked in). Without, floors take the floor colour and
 * walls a shade lighter, darkened a little by which way they face. Both cut away everything above `cut` and leave
 * out the clear box. The 'solid' pass draws everything outside the cutaway; the 'ghost' pass draws only the
 * cutaway, see-through, after everything else.
 */
function scanMaterial(shared: Shared, colored: boolean, pass: 'solid' | 'ghost'): ShaderMaterial {
  return new ShaderMaterial({
    vertexColors: colored, // three defines USE_COLOR (and USE_COLOR_ALPHA for RGBA) and declares `color`
    defines: pass === 'ghost' ? { GHOST_PASS: '' } : {},
    transparent: pass === 'ghost',
    // Both passes write depth: the see-through one draws its triangles in no particular order, and without depth
    // a far face (a desk's dark inside) could land on a near one, which showed as a dark slot while it faded.
    depthWrite: true,
    uniforms: {
      uFloor: { value: new Color(FLOOR) },
      uWall: { value: new Color(0x23272d) },
      uShade: { value: new Color(WALL_SHADE) },
      uCut: shared.cut,
      uLift: shared.lift,
      uClearMin: { value: shared.clear.min },
      uClearMax: { value: shared.clear.max },
      uGhostMin: { value: shared.ghost.min },
      uGhostMax: { value: shared.ghost.max },
      uGhostFade: { value: GHOST_FADE_M },
      uGhostAlpha: { value: GHOST_ALPHA },
      uGhostOn: shared.ghostOn,
    },
    vertexShader: /* glsl */ `
      #include <color_pars_vertex>
      varying vec3 vNormal;
      varying vec3 vWorld;
      void main() {
        #include <color_vertex>
        vec4 world = modelMatrix * vec4(position, 1.0);
        vWorld = world.xyz;
        vNormal = mat3(modelMatrix) * normal;
        gl_Position = projectionMatrix * viewMatrix * world;
      }`,
    fragmentShader: /* glsl */ `
      #include <color_pars_fragment>
      uniform vec3 uFloor;
      uniform vec3 uWall;
      uniform vec3 uShade;
      uniform float uCut;
      uniform float uLift;
      uniform vec3 uClearMin;
      uniform vec3 uClearMax;
      uniform vec3 uGhostMin;
      uniform vec3 uGhostMax;
      uniform float uGhostFade;
      uniform float uGhostAlpha;
      uniform float uGhostOn;
      varying vec3 vNormal;
      varying vec3 vWorld;
      // 0 outside the cutaway, rising to 1 over uGhostFade from its east and west ends, times how far it is on.
      float ghostAt() {
        if (any(lessThan(vWorld, uGhostMin)) || any(greaterThan(vWorld, uGhostMax))) return 0.0;
        float ends = min(vWorld.x - uGhostMin.x, uGhostMax.x - vWorld.x);
        return uGhostOn * smoothstep(0.0, uGhostFade, ends);
      }
      void main() {
        if (vWorld.y > uCut) discard;
        if (all(greaterThan(vWorld, uClearMin)) && all(lessThan(vWorld, uClearMax))) discard;
        float ghost = ghostAt();
        #ifdef GHOST_PASS
          if (ghost <= 0.001) discard;
        #else
          if (ghost > 0.001) discard;
        #endif
        #ifdef USE_COLOR
          vec3 base = vColor.rgb * uLift; // glTF vertex colours are linear, like the rest of the scene
        #else
          vec3 n = normalize(vNormal);
          float up = abs(n.y);
          vec3 base = mix(uWall, uFloor, up);
          base = mix(base, uShade, 0.22 * (1.0 - up) * (0.4 + 0.6 * abs(n.x)));
        #endif
        #ifdef GHOST_PASS
          gl_FragColor = vec4(base, mix(1.0, uGhostAlpha, ghost));
        #else
          gl_FragColor = vec4(base, 1.0);
        #endif
        #include <colorspace_fragment>
      }`,
    polygonOffset: true,
    polygonOffsetFactor: 2,
    polygonOffsetUnits: 2,
  })
}

/** Triangles each GPU draws comfortably: the Pi measured at 1080p, a laptop with room to spare. */
const TRIANGLE_BUDGET: Record<Quality, number> = { pi: 150_000, hi: 400_000 }

/** Puts our material on every mesh (coloured where it has vertex colours) and drops textures, and gives each mesh a
 *  hidden see-through twin for the cutaway. Returns the triangle count and the twins. */
function flatten(root: Object3D, shared: Shared): { triangles: number; twins: Mesh[]; solids: Mesh[] } {
  const solid = { flat: scanMaterial(shared, false, 'solid'), colored: scanMaterial(shared, true, 'solid') }
  const ghost = { flat: scanMaterial(shared, false, 'ghost'), colored: scanMaterial(shared, true, 'ghost') }
  let triangles = 0
  const meshes: Mesh[] = []
  root.traverse((obj) => obj instanceof Mesh && meshes.push(obj))
  const twins = meshes.map((obj) => {
    const old = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const m of old) {
      for (const value of Object.values(m)) if (value instanceof Texture) value.dispose()
      m.dispose()
    }
    if (!obj.geometry.getAttribute('normal')) obj.geometry.computeVertexNormals()
    const kind = obj.geometry.getAttribute('color') ? 'colored' : 'flat'
    obj.material = solid[kind]
    const index = obj.geometry.getIndex()
    triangles += (index ? index.count : obj.geometry.getAttribute('position').count) / 3
    // Drawn after everything else, so the strip, the links and the person behind it show through.
    const twin = new Mesh(obj.geometry, ghost[kind])
    twin.renderOrder = 40
    twin.visible = false
    obj.add(twin)
    return twin
  })
  return { triangles, twins, solids: meshes }
}

/** How far around the layout's middle under() looks for what a device stands on. */
const NEAR_M = 4

/** The triangles of the placed model within NEAR_M (east and north) of the scene's middle, nine numbers each
 *  (three corners, scene coordinates). One pass over the model; a few thousand of its triangles are left. */
function nearTriangles(solids: readonly Mesh[], holder: Object3D): Float32Array {
  holder.updateMatrixWorld(true)
  const out: number[] = []
  const v = [new Vector3(), new Vector3(), new Vector3()]
  for (const mesh of solids) {
    const pos = mesh.geometry.getAttribute('position')
    const index = mesh.geometry.getIndex()
    const count = index ? index.count : pos.count
    for (let i = 0; i < count; i += 3) {
      for (let k = 0; k < 3; k++) v[k].fromBufferAttribute(pos, index ? index.getX(i + k) : i + k).applyMatrix4(mesh.matrixWorld)
      if (Math.min(v[0].x, v[1].x, v[2].x) > NEAR_M || Math.max(v[0].x, v[1].x, v[2].x) < -NEAR_M) continue
      if (Math.min(v[0].z, v[1].z, v[2].z) > NEAR_M || Math.max(v[0].z, v[1].z, v[2].z) < -NEAR_M) continue
      for (const p of v) out.push(p.x, p.y, p.z)
    }
  }
  return new Float32Array(out)
}

/**
 * The highest surface among `tris` (nearTriangles) straight under the scene point (x, z), at or below `top`, as a
 * scene height; null when none is there. Points of the surface inside `skip` (what the clear box leaves out of the
 * drawing) don't count.
 */
export function surfaceUnder(tris: Float32Array, x: number, z: number, top: number, skip?: Box3): number | null {
  let best: number | null = null
  const at = new Vector3()
  for (let i = 0; i < tris.length; i += 9) {
    const [ax, ay, az, bx, by, bz, cx, cy, cz] = [tris[i], tris[i + 1], tris[i + 2], tris[i + 3], tris[i + 4], tris[i + 5], tris[i + 6], tris[i + 7], tris[i + 8]]
    if (x < Math.min(ax, bx, cx) || x > Math.max(ax, bx, cx) || z < Math.min(az, bz, cz) || z > Math.max(az, bz, cz)) continue
    // Barycentric weights of (x, z) in the triangle seen from above; a triangle on edge has no area there.
    const d = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
    if (Math.abs(d) < 1e-9) continue
    const u = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / d
    const w = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / d
    if (u < 0 || w < 0 || u + w > 1) continue
    const y = u * ay + w * by + (1 - u - w) * cy
    if (y > top + 1e-3 || (best !== null && y <= best)) continue
    if (skip?.containsPoint(at.set(x, y, z))) continue
    best = y
  }
  return best
}

/** ?lift=1.2 brightens the hall model's own colours (a projector washes dark tones out); 1 when not set. Only
 *  the model's baked colours change, never the room's palette, and it is kept between 0.5 and 2. */
export function hallLift(params: URLSearchParams): number {
  const v = Number(params.get('lift'))
  return Number.isFinite(v) && v >= 0.5 && v <= 2 ? v : 1
}

/** Loads the scan if there is one. Resolves to it once it stands in for the drawn room, else to null. */
export async function loadScan(view: RoomView, drawnRoom: Object3D, params: URLSearchParams, quality: Quality): Promise<Scan | null> {
  if (params.get('scan') === '0') return null
  const source = await scanSource()
  const url = source && scanUrl(source, quality, params.get('hall'))
  if (!source || !url) return null
  try {
    // Loaded only when there is a scan, so builds without one stay small.
    const [{ GLTFLoader }, { MeshoptDecoder }] = await Promise.all([
      import('three/addons/loaders/GLTFLoader.js'),
      import('three/addons/libs/meshopt_decoder.module.js'),
    ])
    const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
    const gltf = await loader.loadAsync(url)
    const box = new Box3().setFromObject(gltf.scene)
    const cut = { value: DEFAULT_CUT_M }
    const shared: Shared = { cut, lift: { value: hallLift(params) }, clear: clearBox(), ghost: ghostBox(), ghostOn: { value: 0 } }
    const { triangles, twins, solids } = flatten(gltf.scene, shared)
    // The model's triangles near the layout, in scene coordinates, for under(): gathered once per placement.
    let near: Float32Array | null = null
    if (triangles > TRIANGLE_BUDGET[quality]) {
      console.warn(
        `room scan: ${Math.round(triangles)} triangles, over the ${quality} budget of ${TRIANGLE_BUDGET[quality]}. ` +
          'Shrink it: npm run scan:prep -- <file.glb> --max 100000',
      )
    }
    const holder = new Group()
    holder.add(gltf.scene)
    view.scene.add(holder)
    const handle: Scan = {
      fit: source.fit,
      apply(fit) {
        handle.fit = fit
        near = null
        const p = placeScan(box.min.toArray(), box.max.toArray(), fit)
        gltf.scene.position.set(...p.inner)
        holder.scale.setScalar(p.scale)
        holder.rotation.y = p.yaw
        holder.position.set(...p.outer)
        cut.value = p.cut
        // Where the hall stands now, for the page's own checks (the browser tests read it).
        view.host.dataset.scanAt = [...(fit.offset_m ?? [0, 0]), fit.yaw_deg ?? 0].join(',')
        view.requestRender()
      },
      bounds: () => new Box3().setFromObject(holder),
      ghost(amount) {
        const a = Math.min(1, Math.max(0, amount))
        if (a === shared.ghostOn.value) return
        shared.ghostOn.value = a
        for (const t of twins) t.visible = a > 0 // no second pass while nothing is see-through
        view.requestRender()
      },
      box: { min: box.min.toArray(), max: box.max.toArray() },
      under(x, z, top) {
        near ??= nearTriangles(solids, holder)
        return surfaceUnder(near, x, z, top, shared.clear)
      },
    }
    handle.apply(source.fit)
    drawnRoom.visible = false
    view.host.dataset.scan = 'loaded'
    view.host.dataset.scanFile = url.split('/').pop()
    return handle
  } catch (err) {
    console.warn('room scan: could not load, keeping the drawn room.', err)
    view.host.dataset.scan = 'failed'
    return null
  }
}
