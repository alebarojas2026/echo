import { Box3, Color, Group, Mesh, ShaderMaterial, Texture, type Object3D } from 'three'
import { FLOOR, WALL_SHADE } from './palette'
import type { RoomView } from './view'

// The scanned room (web/public/models/room.glb), drawn flat in the room's colours instead of the drawn walls.
// vite.config.ts sets __ROOM_SCAN__ at build time only when the file exists, so a board without a scan
// never asks for it. ?scan=0 keeps the drawn room. Alignment comes from web/public/models/room.json, made by
// lining the scan up by eye with ?align=1 (align.ts). Under `vite` the screen asks the dev server instead
// (/__room-scan), so a new scan or alignment shows on reload without a restart.

/** A loaded scan that can be moved: align mode calls `apply` on every key. */
export interface Scan {
  /** The alignment shown now. */
  fit: ScanFit
  apply(fit: ScanFit): void
}

type ScanSource = { url: string; fit: ScanFit } | null

/** Where the scan and its alignment are: the dev server's current answer, or what the build found. */
async function scanSource(): Promise<ScanSource> {
  if (!import.meta.env.DEV) return __ROOM_SCAN__
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

/** Floors take the floor colour, walls a shade lighter, darkened a little by which way they face. */
function scanMaterial(cut: number): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: {
      uFloor: { value: new Color(FLOOR) },
      uWall: { value: new Color(0x23272d) },
      uShade: { value: new Color(WALL_SHADE) },
      uCut: { value: cut },
    },
    vertexShader: /* glsl */ `
      varying vec3 vNormal;
      varying float vHeight;
      void main() {
        vec4 world = modelMatrix * vec4(position, 1.0);
        vHeight = world.y;
        vNormal = mat3(modelMatrix) * normal;
        gl_Position = projectionMatrix * viewMatrix * world;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uFloor;
      uniform vec3 uWall;
      uniform vec3 uShade;
      uniform float uCut;
      varying vec3 vNormal;
      varying float vHeight;
      void main() {
        if (vHeight > uCut) discard;
        vec3 n = normalize(vNormal);
        float up = abs(n.y);
        vec3 base = mix(uWall, uFloor, up);
        base = mix(base, uShade, 0.22 * (1.0 - up) * (0.4 + 0.6 * abs(n.x)));
        gl_FragColor = vec4(base, 1.0);
        #include <colorspace_fragment>
      }`,
    polygonOffset: true,
    polygonOffsetFactor: 2,
    polygonOffsetUnits: 2,
  })
}

const TRIANGLE_BUDGET = 150_000

/** Replaces every material with `material` and drops textures. Returns the triangle count. */
function flatten(root: Object3D, material: ShaderMaterial): number {
  let triangles = 0
  root.traverse((obj) => {
    if (!(obj instanceof Mesh)) return
    const old = Array.isArray(obj.material) ? obj.material : [obj.material]
    for (const m of old) {
      for (const value of Object.values(m)) if (value instanceof Texture) value.dispose()
      m.dispose()
    }
    if (!obj.geometry.getAttribute('normal')) obj.geometry.computeVertexNormals()
    obj.material = material
    const index = obj.geometry.getIndex()
    triangles += (index ? index.count : obj.geometry.getAttribute('position').count) / 3
  })
  return triangles
}

/** Loads the scan if there is one. Resolves to it once it stands in for the drawn room, else to null. */
export async function loadScan(view: RoomView, drawnRoom: Object3D, params: URLSearchParams): Promise<Scan | null> {
  if (params.get('scan') === '0') return null
  const scan = await scanSource()
  if (!scan) return null
  try {
    // Loaded only when there is a scan, so builds without one stay small.
    const [{ GLTFLoader }, { MeshoptDecoder }] = await Promise.all([
      import('three/addons/loaders/GLTFLoader.js'),
      import('three/addons/libs/meshopt_decoder.module.js'),
    ])
    const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
    const gltf = await loader.loadAsync(scan.url)
    const box = new Box3().setFromObject(gltf.scene)
    const material = scanMaterial(placeScan(box.min.toArray(), box.max.toArray(), scan.fit).cut)
    const triangles = flatten(gltf.scene, material)
    if (triangles > TRIANGLE_BUDGET) {
      console.warn(
        `room scan: ${Math.round(triangles)} triangles, over the Pi budget of ${TRIANGLE_BUDGET}. ` +
          'Shrink it: npx @gltf-transform/cli simplify room.glb room.glb --ratio 0.25 && npx @gltf-transform/cli meshopt room.glb room.glb',
      )
    }
    const holder = new Group()
    holder.add(gltf.scene)
    view.scene.add(holder)
    const handle: Scan = {
      fit: scan.fit,
      apply(fit) {
        handle.fit = fit
        const p = placeScan(box.min.toArray(), box.max.toArray(), fit)
        gltf.scene.position.set(...p.inner)
        holder.scale.setScalar(p.scale)
        holder.rotation.y = p.yaw
        holder.position.set(...p.outer)
        material.uniforms.uCut.value = p.cut
        view.requestRender()
      },
    }
    handle.apply(scan.fit)
    drawnRoom.visible = false
    view.host.dataset.scan = 'loaded'
    return handle
  } catch (err) {
    console.warn('room scan: could not load, keeping the drawn room.', err)
    view.host.dataset.scan = 'failed'
    return null
  }
}
