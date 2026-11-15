import { Color, CylinderGeometry, Group, Object3D, ShaderMaterial, type Material, BoxGeometry, BufferGeometry, Float32BufferAttribute, LineBasicMaterial, LineSegments, Mesh, MeshBasicMaterial, Plane, Raycaster, Vector2, Vector3 } from 'three'
import type { HallLink } from './contract'
import { HALL_BEACONS, SIZE_M, type HallBeacon, type Vec3 } from './frame'
import { fade, Held } from './motion'
import { EDGE, TEXT } from './palette'
import { v3 } from './stage'
import type { RoomView } from './view'

// Hall beacons: radios far outside the layout (nodes.json hall.beacons). Like every device they are drawn only
// while the board hears them (a hall row from them that isn't stale) and only where someone has placed them. A
// beacon that is heard but has no position yet waits in a small tray ("1 new beacon: H"). In align mode a beacon
// can be picked (Tab, or a click on it), moved (arrows, or dragged, from the tray too) and saved with S.

const HEAD_M = 0.12
/** The height a beacon gets when it is placed by hand: the contract's antennas are 1 m up. */
const PLACED_Z_M = 1.0
const ON_MS = 300
const OFF_MS = 2500

/** The hall beacons heard now: a hall row from them with readings that isn't stale. */
export function hallHeard(rows: readonly HallLink[] | undefined): Set<string> {
  return new Set((rows ?? []).filter((r) => !r.stale && (r.rate_hz ?? 0) > 0).map((r) => r.tx))
}

/** The tray's words for heard beacons with no position: "1 new beacon: H", "2 new beacons: H, J", or ''. */
export function trayText(waiting: readonly HallBeacon[]): string {
  if (!waiting.length) return ''
  return `${waiting.length} new beacon${waiting.length > 1 ? 's' : ''}: ${waiting.map((b) => b.id).join(', ')}`
}

interface Item {
  b: HallBeacon
  head: Mesh<BoxGeometry, MeshBasicMaterial>
  post: LineSegments<BufferGeometry, LineBasicMaterial>
  label: HTMLElement
  held: Held<boolean>
  heard: boolean
  alpha: number
}

export class HallBeacons {
  /** The beacon align mode is moving, or null. */
  selected: string | null = null
  private readonly items: Item[] = []
  private readonly tray: HTMLElement
  private editing = false
  private dragging: string | null = null
  private onChange: () => void = () => {}

  constructor(private readonly view: RoomView) {
    const geom = new BoxGeometry(HEAD_M, HEAD_M, HEAD_M)
    for (const b of HALL_BEACONS) {
      const head = new Mesh(geom, new MeshBasicMaterial({ color: TEXT, transparent: true, opacity: 0 }))
      const postGeom = new BufferGeometry()
      postGeom.setAttribute('position', new Float32BufferAttribute([0, 0, 0, 0, 0, 0], 3))
      const post = new LineSegments(postGeom, new LineBasicMaterial({ color: EDGE, transparent: true, opacity: 0 }))
      head.visible = post.visible = false
      head.userData.beacon = b.node
      view.scene.add(head, post)
      const label = view.addLabel(`Beacon ${b.id}`, new Vector3(), 'room-label--node room-label--right')
      label.hidden = true
      this.items.push({ b, head, post, label, held: new Held<boolean>(false, (on) => (on ? ON_MS : OFF_MS)), heard: false, alpha: 0 })
    }
    this.tray = document.createElement('div')
    this.tray.className = 'room-tray'
    this.tray.hidden = true
    view.host.append(this.tray)
    for (const it of this.items) this.put(it)
    view.addAnimator((dt) => this.ease(dt))
  }

  /** Who is heard now (state.hall), held so a missed reading never makes a beacon blink. */
  update(rows: readonly HallLink[] | undefined, nowMs = performance.now()) {
    const now = hallHeard(rows)
    for (const it of this.items) it.heard = it.held.update(now.has(it.b.node), nowMs)
    this.refresh()
  }

  /** Align mode: the tray's beacons can be dragged onto the model, and placed ones clicked and dragged. */
  startEditing(onChange: () => void) {
    this.editing = true
    this.onChange = onChange
    const canvas = this.view.renderer.domElement
    canvas.addEventListener('pointerdown', (e) => {
      const hit = this.pick(e)
      if (!hit) return
      this.select(hit)
      this.dragging = hit
      canvas.setPointerCapture(e.pointerId)
    })
    canvas.addEventListener('pointermove', (e) => {
      if (this.dragging) this.dropAt(this.dragging, e)
    })
    window.addEventListener('pointerup', (e) => {
      if (this.dragging && e.target === canvas) this.dropAt(this.dragging, e)
      this.dragging = null
    })
    this.refresh()
  }

  /** The heard beacons, in file order: the ones Tab steps through. */
  heardNodes(): string[] {
    return this.items.filter((it) => it.heard).map((it) => it.b.node)
  }

  select(node: string | null) {
    this.selected = node
    for (const it of this.items) it.label.classList.toggle('room-label--selected', it.b.node === node)
    this.view.host.dataset.selected = node ?? ''
    this.onChange()
    this.view.requestRender()
  }

  /** Tab: the next heard beacon, then none. */
  cycle() {
    const nodes = this.heardNodes()
    const i = this.selected ? nodes.indexOf(this.selected) : -1
    this.select(i + 1 < nodes.length ? nodes[i + 1] : null)
  }

  /** Moves the selected beacon on the floor (contract metres, east and north). An unplaced one starts 2 m north
   *  of the layout. */
  nudge(dx: number, dy: number) {
    const it = this.items.find((i) => i.b.node === this.selected)
    if (!it) return
    const [x, y, z] = it.b.xyz ?? [SIZE_M[0] / 2, SIZE_M[1] + 2, PLACED_Z_M]
    this.place(it, [Number((x + dx).toFixed(2)), Number((y + dy).toFixed(2)), z])
  }

  /** Every beacon's position, for saving to nodes.json. */
  positions(): { node: string; xyz_m: Vec3 | null }[] {
    return this.items.map((it) => ({ node: it.b.node, xyz_m: it.b.xyz }))
  }

  /** Words for the align panel: the selected beacon and where it is. */
  describe(): string {
    const it = this.items.find((i) => i.b.node === this.selected)
    if (!it) return ''
    const at = it.b.xyz ? `${it.b.xyz[0].toFixed(2)} m east, ${it.b.xyz[1].toFixed(2)} m north` : 'not placed yet'
    return `Beacon ${it.b.id}: ${at}`
  }

  private place(it: Item, xyz: Vec3) {
    it.b.xyz = xyz
    this.put(it)
    this.refresh()
    this.onChange()
  }

  /** The beacon under the pointer, if any. */
  private pick(e: PointerEvent): string | null {
    const ray = this.ray(e)
    const heads = this.items.filter((it) => it.head.visible).map((it) => it.head)
    return (ray.intersectObjects(heads)[0]?.object.userData.beacon as string | undefined) ?? null
  }

  /** Puts `node` where the pointer meets the floor. */
  private dropAt(node: string, e: PointerEvent) {
    const it = this.items.find((i) => i.b.node === node)
    const hit = this.ray(e).ray.intersectPlane(new Plane(new Vector3(0, 1, 0), 0), new Vector3())
    if (!it || !hit) return
    // Scene back to the contract frame (frame.ts toScene, inverted).
    this.place(it, [Number((hit.x + SIZE_M[0] / 2).toFixed(2)), Number((SIZE_M[1] / 2 - hit.z).toFixed(2)), it.b.xyz?.[2] ?? PLACED_Z_M])
  }

  private ray(e: PointerEvent): Raycaster {
    const rect = this.view.renderer.domElement.getBoundingClientRect()
    const ndc = new Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    const ray = new Raycaster()
    ray.setFromCamera(ndc, this.view.camera)
    return ray
  }

  private put(it: Item) {
    if (!it.b.xyz) return
    const top = v3(it.b.xyz)
    it.head.position.copy(top)
    const base = v3([it.b.xyz[0], it.b.xyz[1], 0])
    const pos = it.post.geometry.getAttribute('position') as Float32BufferAttribute
    pos.set([base.x, base.y, base.z, top.x, top.y, top.z])
    pos.needsUpdate = true
    it.post.geometry.computeBoundingSphere()
    this.view.moveLabel(it.label, v3([it.b.xyz[0] + HEAD_M / 2, it.b.xyz[1], it.b.xyz[2]]))
  }

  /** The tray and the test mirror, after hearing or placing changes. */
  private refresh() {
    const waiting = this.items.filter((it) => it.heard && !it.b.xyz).map((it) => it.b)
    this.tray.replaceChildren()
    if (waiting.length) {
      const words = document.createElement('span')
      words.textContent = trayText(waiting)
      this.tray.append(words)
      // In align mode each waiting beacon is a chip to drag onto the model.
      if (this.editing) {
        for (const b of waiting) {
          const chip = document.createElement('button')
          chip.type = 'button'
          chip.className = 'room-tray-chip'
          chip.textContent = b.id
          chip.addEventListener('pointerdown', (e) => {
            e.preventDefault()
            this.select(b.node)
            this.dragging = b.node
          })
          this.tray.append(chip)
        }
      }
    }
    this.tray.hidden = !waiting.length
    this.view.host.dataset.hallBeacons = this.items.filter((it) => it.heard && it.b.xyz).map((it) => it.b.node).join(',')
    this.view.host.dataset.hallWaiting = waiting.map((b) => b.node).join(',')
    this.view.requestRender()
  }

  private ease(dt: number): boolean {
    let busy = false
    for (const it of this.items) {
      const to = it.heard && it.b.xyz ? 1 : 0
      it.alpha = fade(it.alpha, to, dt)
      busy ||= it.alpha !== to
      it.head.material.opacity = it.post.material.opacity = it.alpha
      it.head.visible = it.post.visible = it.alpha > 0
      it.head.scale.setScalar(it.b.node === this.selected ? 1.5 : 1)
      it.label.style.opacity = String(it.alpha)
      it.label.hidden = it.alpha === 0
    }
    return busy
  }
}

import { DEVICE, DEVICE_DETAIL, FAULT, WALL_SHADE } from './palette'
import { LIGHT } from './shade'
import phoneUrl from './assets/phone.glb?url'
import pi5Url from './assets/pi5.glb?url'
import standUrl from './assets/stand.glb?url'
import unoqUrl from './assets/unoq.glb?url'

// The radio nodes as small scale models: the UNO Q, Pi cases, phones on the square, and schematic
// ESP32 beacons on the desk. Each sits on a slim stand or arm. The models are web/src/room/assets/*.glb, built by
// tools/devices/build.py: real-size meshes with ambient occlusion baked into vertex colours, no textures.
//
// createDevice() returns an Object3D whose origin is the foot of its stand or arm. It faces +z, so the caller
// turns it (rotation.y) to face the square's centre. Its child "anchor" is the node's radio centre: it sits
// at the node's height (1 m, or whatever setDeviceHeight says), straight above the origin, so the links,
// which end at the node's position, end on the device.
//
// Geometry and base materials are shared; a node gets its own material pair when fading or showing tamper. They are unlit like the
// rest of the room: each surface takes a tone between a dark and a light grey from one fixed light up and to
// the north-west (the same light as the room's baked shading), times its baked occlusion.

export type DeviceKind = 'unoq' | 'pi5' | 'phone' | 'beacon'
type ModelName = Exclude<DeviceKind, 'beacon'> | 'stand'

/** How much bigger than life the devices and their stands are drawn, so they read from across the room.
 *  Heights don't scale: a device's anchor still sits at its node's real height. */
export const DISPLAY_SCALE = 2.5

/** A node's radio height when nodes.json doesn't say otherwise, in metres. */
export const NODE_HEIGHT_M = 1.0


/** Each model's extent around its anchor, in real metres: x across (to your right as you face it), y up,
 *  z out of its front. devices.test.ts checks these against the model files; labels and stand-ins use them. */
export const DEVICE_BOUNDS: Record<DeviceKind, { min: Vec3; max: Vec3 }> = {
  unoq: { min: [-0.0349, -0.0231, -0.0243], max: [0.0343, 0.0227, 0.0248] },
  pi5: { min: [-0.0351, -0.03, -0.0492], max: [0.0352, 0.0166, 0.0492] },
  beacon: { min: [-0.014, -0.004, -0.026], max: [0.014, 0.009, 0.026] },
  phone: { min: [-0.0366, -0.09, -0.0306], max: [0.0366, 0.069, 0.0437] },
}

const URLS: Record<ModelName, string> = { unoq: unoqUrl, pi5: pi5Url, phone: phoneUrl, stand: standUrl }

const VERTEX = /* glsl */ `
  #include <common>
  #include <color_pars_vertex>
  varying vec3 vNormalW;
  void main() {
    #include <color_vertex>
    vNormalW = mat3(modelMatrix) * normal;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`

const FRAGMENT = /* glsl */ `
  uniform vec3 uLight;
  uniform vec3 uDark;
  uniform vec3 uLightDir;
  uniform float uTop;
  uniform float uAlpha;
  uniform float uFault;
  uniform vec3 uFaultColor;
  varying vec3 vNormalW;
  #include <color_pars_fragment>
  void main() {
    float k = min(1.0, max(0.0, dot(normalize(vNormalW), uLightDir)) / uTop);
    float occlusion = 1.0;
    #if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
      occlusion = vColor.r;
    #endif
    vec3 tone = mix(uDark, uLight, k) * occlusion;
    gl_FragColor = vec4(mix(tone, uFaultColor * (0.55 + k * 0.45), uFault), uAlpha);
    #include <colorspace_fragment>
  }`

/** A material whose surfaces run from `dark` (facing away from the light) to `light` (facing up). */
function toneMaterial(light: number, darkMix: number): ShaderMaterial {
  return new ShaderMaterial({
    name: 'device-tone',
    uniforms: {
      uLight: { value: new Color(light) },
      uDark: { value: new Color(light).lerp(new Color(WALL_SHADE), darkMix) },
      uLightDir: { value: LIGHT.clone() },
      uAlpha: { value: 1 },
      uFault: { value: 0 },
      uFaultColor: { value: new Color(FAULT) },
      uTop: { value: LIGHT.y }, // what a surface facing straight up receives: it takes the light tone
    },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    vertexColors: true,
  })
}

let materials: Record<'device' | 'detail', ShaderMaterial> | null = null

/** The two materials every device shares, by the names the model files give them. */
export function deviceMaterials(): Record<'device' | 'detail', ShaderMaterial> {
  materials ??= { device: toneMaterial(DEVICE, 0.5), detail: toneMaterial(DEVICE_DETAIL, 0.55) }
  return materials
}

interface Model {
  root: Object3D
  /** Where the pole meets the device, metres below the anchor (real size, so negative). */
  mount: number
}

const models = new Map<ModelName, Promise<Model | null>>()

/** Loads a model file once and swaps its materials for the shared ones. Resolves null if it can't load. */
function loadModel(name: ModelName): Promise<Model | null> {
  let p = models.get(name)
  if (!p) {
    p = (async () => {
      try {
        const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js')
        const res = await fetch(URLS[name])
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const gltf = await new GLTFLoader().parseAsync(await res.arrayBuffer(), '')
        const shared = deviceMaterials()
        gltf.scene.traverse((o) => {
          if (!(o instanceof Mesh)) return
          const old = o.material as Material
          o.material = old.name === 'detail' ? shared.detail : shared.device
          old.dispose()
        })
        const mount = gltf.scene.getObjectByName('mount')?.position.y ?? 0
        for (const point of ['anchor', 'mount']) gltf.scene.getObjectByName(point)?.removeFromParent()
        return { root: gltf.scene, mount }
      } catch (err) {
        console.warn(`devices: could not load ${name}, drawing a plain stand-in.`, err)
        return null
      }
    })()
    models.set(name, p)
  }
  return p
}

/** Resolves once every device file has loaded (or failed and fallen back to a stand-in). */
export function devicesLoaded(): Promise<void> {
  return Promise.all((Object.keys(URLS) as ModelName[]).map(loadModel)).then(() => undefined)
}

interface DeviceParts {
  kind: DeviceKind
  head: Group
  foot: Object3D | null
  pole: Object3D | null
  mount: number
  heightM: number
  appearance?: Record<'device' | 'detail', ShaderMaterial>
}

/** Each device's parts, kept beside it rather than in userData, which three.js copies as JSON on clone. */
const deviceParts = new WeakMap<Object3D, DeviceParts>()

function parts(device: Object3D): DeviceParts {
  const p = deviceParts.get(device)
  if (!p) throw new Error('not a device made by createDevice()')
  return p
}

/** Stretches the pole from the floor to the device's mount point. */
function fitPole(p: DeviceParts) {
  if (!p.pole) return
  const tip = p.head.position.clone().add(new Vector3(0, DISPLAY_SCALE * p.mount, 0))
  p.pole.scale.set(DISPLAY_SCALE, Math.max(0.01, tip.length()), DISPLAY_SCALE)
  p.pole.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), tip.normalize())
}

let fallbackGeometry: Record<DeviceKind, BufferGeometry> | null = null

/** The plain box drawn when a model file can't load: the device's size, so the room still reads. */
function standIn(kind: DeviceKind): Mesh {
  fallbackGeometry ??= Object.fromEntries(
    (Object.keys(DEVICE_BOUNDS) as DeviceKind[]).map((k) => {
      const { min, max } = DEVICE_BOUNDS[k]
      const g = new BoxGeometry(max[0] - min[0], max[1] - min[1], max[2] - min[2])
      g.translate((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2)
      return [k, unshaded(g)]
    }),
  ) as Record<DeviceKind, BufferGeometry>
  return new Mesh(fallbackGeometry[kind], deviceMaterials().device)
}

let fallbackPole: { pole: BufferGeometry; foot: BufferGeometry } | null = null

function unshaded(g: BufferGeometry): BufferGeometry {
  g.setAttribute('color', new Float32BufferAttribute(new Float32Array(g.getAttribute('position').count * 3).fill(1), 3))
  return g
}

/**
 * A device on its stand, origin on the floor under the stand, facing +z. The model files load in the
 * background (once for all devices); onReady(true) runs when this one is drawn from its file, onReady(false)
 * when it fell back to a plain box. Either way the caller should draw a new frame then.
 */
export function createDevice(kind: DeviceKind, onReady?: (loaded: boolean) => void): Object3D {
  const device = new Group()
  device.name = `device-${kind}`
  const head = new Group()
  head.name = 'head'
  head.scale.setScalar(DISPLAY_SCALE)
  const anchor = new Object3D()
  anchor.name = 'anchor'
  head.add(anchor)
  device.add(head)
  const p: DeviceParts = { kind, head, foot: null, pole: null, mount: 0, heightM: NODE_HEIGHT_M }
  deviceParts.set(device, p)
  head.position.y = p.heightM

  void Promise.all([kind === 'beacon' ? Promise.resolve(beaconModel()) : loadModel(kind), loadModel('stand')]).then(([model, stand]) => {
    if (model) {
      head.add(model.root.clone())
      p.mount = model.mount
    } else {
      head.add(standIn(kind))
      p.mount = DEVICE_BOUNDS[kind].min[1]
    }
    const foot = stand?.root.getObjectByName('foot')
    const pole = stand?.root.getObjectByName('pole')
    if (foot && pole) {
      p.foot = foot.clone()
      p.pole = pole.clone()
    } else {
      fallbackPole ??= {
        pole: unshaded(new CylinderGeometry(0.0035, 0.0035, 1, 12, 1, true).translate(0, 0.5, 0)),
        foot: unshaded(new CylinderGeometry(0.0145, 0.0145, 0.004, 24).translate(0, 0.002, 0)),
      }
      p.foot = new Mesh(fallbackPole.foot, deviceMaterials().detail)
      p.pole = new Mesh(fallbackPole.pole, deviceMaterials().detail)
    }
    p.foot.scale.setScalar(DISPLAY_SCALE)
    p.foot.position.set(0, 0, 0)
    p.pole.position.set(0, 0, 0)
    device.add(p.foot, p.pole)
    fitPole(p)
    if (p.appearance) applyAppearance(device, p.appearance)
    onReady?.(Boolean(model && stand))
  })
  return device
}

/** Puts the device's anchor (its radio's centre) this many metres above the floor; the pole follows. */
export function setDeviceHeight(device: Object3D, heightM: number, offset = new Vector3()) {
  const p = parts(device)
  p.heightM = heightM
  p.head.position.copy(offset).setY(heightM)
  fitPole(p)
}

const Y_AXIS = new Vector3(0, 1, 0)
const corner = new Vector3()

/**
 * Where a node's name goes, in the device's parent's frame: just above the device ('above'), or level with
 * its anchor just past its right or left side as the room's camera sees it (+x or -x). Uses the device's
 * current position, height and turn, and its size from DEVICE_BOUNDS, so it is right before the file loads.
 */
export function deviceLabelPoint(device: Object3D, side: 'above' | 'right' | 'left'): Vector3 {
  const p = parts(device)
  const { min, max } = DEVICE_BOUNDS[p.kind]
  const at = p.head.position.clone().applyAxisAngle(Y_AXIS, device.rotation.y).add(device.position)
  if (side === 'above') return at.setY(at.y + max[1] * DISPLAY_SCALE)
  let reach = side === 'right' ? -Infinity : Infinity
  for (let i = 0; i < 4; i++) {
    corner.set(i & 1 ? max[0] : min[0], 0, i & 2 ? max[2] : min[2]).applyAxisAngle(Y_AXIS, device.rotation.y)
    reach = side === 'right' ? Math.max(reach, corner.x) : Math.min(reach, corner.x)
  }
  return at.setX(at.x + reach * DISPLAY_SCALE)
}

// The desk's small ESP32 beacons use a schematic board silhouette, not a measured hardware model.
let beacon: Model | undefined
function beaconModel(): Model {
  if (beacon) return beacon
  const root = new Group()
  const shared = deviceMaterials()
  const block = (size: Vec3, at: Vec3, detail = false) => {
    const mesh = new Mesh(unshaded(new BoxGeometry(...size)), detail ? shared.detail : shared.device)
    mesh.position.set(...at)
    root.add(mesh)
  }
  block([.028,.004,.052], [0,-.002,0], true)
  block([.019,.009,.023], [0,.0045,-.003])
  block([.008,.005,.006], [0,.0025,.023])
  for (const x of [-.012,.012]) block([.002,.006,.03], [x,.003,0])
  for (let i = 0; i < 3; i++) block([.015,.001,.001], [0,.0005,-.019-i*.002])
  return beacon = { root, mount: -.004 }
}

function applyAppearance(device: Object3D, appearance: Record<'device' | 'detail', ShaderMaterial>) {
  const shared = deviceMaterials()
  device.traverse(o => {
    if (o instanceof Mesh) o.material = o.material === shared.device || o.material === appearance.device ? appearance.device : appearance.detail
  })
}

/** Each node fades and reports tamper independently while keeping the geometry shared. */
export function setDeviceAppearance(device: Object3D, alpha: number, fault: boolean) {
  const p = parts(device)
  if (!p.appearance) {
    const shared = deviceMaterials()
    p.appearance = { device: shared.device.clone(), detail: shared.detail.clone() }
    applyAppearance(device, p.appearance)
  }
  for (const material of Object.values(p.appearance)) {
    material.uniforms.uAlpha.value = alpha
    material.uniforms.uFault.value = fault ? 1 : 0
    if (material.transparent !== (alpha < 1)) { material.transparent = alpha < 1; material.needsUpdate = true }
    material.depthWrite = alpha === 1
  }
}
