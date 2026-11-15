import { Box3, Color, Group, Mesh, ShaderMaterial, Texture, type Object3D } from 'three'
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
}

export type ScanSource = { hi?: string; lo?: string; fit: ScanFit } | null

/** The model for this quality: hi takes the detailed one when there is one, pi the light one. */
export function scanUrl(source: NonNullable<ScanSource>, quality: Quality): string | undefined {
  return quality === 'hi' ? (source.hi ?? source.lo) : (source.lo ?? source.hi)
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
    outer: [dx, -0.03, -dy], // 3 cm under our floor marks, so a bumpy scanned floor never pokes through them
    yaw: ((fit.yaw_deg ?? 0) * Math.PI) / 180,
    scale,
    cut: fit.cut_m ?? DEFAULT_CUT_M,
  }
}

/**
 * With `colored`, the model's own vertex colours (shading baked in). Without, floors take the floor colour and
 * walls a shade lighter, darkened a little by which way they face. Both cut away everything above `cut`.
 */
function scanMaterial(cut: { value: number }, colored: boolean, lift = 1): ShaderMaterial {
  return new ShaderMaterial({
    vertexColors: colored, // three defines USE_COLOR (and USE_COLOR_ALPHA for RGBA) and declares `color`
    uniforms: {
      uFloor: { value: new Color(FLOOR) },
      uWall: { value: new Color(0x23272d) },
      uShade: { value: new Color(WALL_SHADE) },
      uCut: cut,
      uLift: { value: lift },
    },
    vertexShader: /* glsl */ `
      #include <color_pars_vertex>
      varying vec3 vNormal;
      varying float vHeight;
      void main() {
        #include <color_vertex>
        vec4 world = modelMatrix * vec4(position, 1.0);
        vHeight = world.y;
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
      varying vec3 vNormal;
      varying float vHeight;
      void main() {
        if (vHeight > uCut) discard;
        #ifdef USE_COLOR
          vec3 base = vColor.rgb * uLift; // glTF vertex colours are linear, like the rest of the scene
        #else
          vec3 n = normalize(vNormal);
          float up = abs(n.y);
          vec3 base = mix(uWall, uFloor, up);
          base = mix(base, uShade, 0.22 * (1.0 - up) * (0.4 + 0.6 * abs(n.x)));
        #endif
        gl_FragColor = vec4(base, 1.0);
        #include <colorspace_fragment>
      }`,
    polygonOffset: true,
    polygonOffsetFactor: 2,
    polygonOffsetUnits: 2,
  })
}

/** Triangles each GPU draws comfortably: the Pi measured at 1080p, a laptop with room to spare. */
const TRIANGLE_BUDGET: Record<Quality, number> = { pi: 150_000, hi: 400_000 }

/** Puts our material on every mesh (coloured where it has vertex colours) and drops textures. Returns the triangle count. */
function flatten(root: Object3D, cut: { value: number }, lift = 1): number {
  const flat = scanMaterial(cut, false)
  const colored = scanMaterial(cut, true, lift)
  let triangles = 0
  root.traverse((obj) => {
    if (!(obj instanceof Mesh)) return
    const old = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const m of old) {
      for (const value of Object.values(m)) if (value instanceof Texture) value.dispose()
      m.dispose()
    }
    if (!obj.geometry.getAttribute('normal')) obj.geometry.computeVertexNormals()
    obj.material = obj.geometry.getAttribute('color') ? colored : flat
    const index = obj.geometry.getIndex()
    triangles += (index ? index.count : obj.geometry.getAttribute('position').count) / 3
  })
  return triangles
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
  const url = source && scanUrl(source, quality)
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
    const triangles = flatten(gltf.scene, cut, hallLift(params))
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
        const p = placeScan(box.min.toArray(), box.max.toArray(), fit)
        gltf.scene.position.set(...p.inner)
        holder.scale.setScalar(p.scale)
        holder.rotation.y = p.yaw
        holder.position.set(...p.outer)
        cut.value = p.cut
        view.requestRender()
      },
      bounds: () => new Box3().setFromObject(holder),
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
