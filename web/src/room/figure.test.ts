import { MeshMatcapMaterial, ShaderLib, SkinnedMesh, type Object3D } from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CROSSFADE_MS, FIGURE_SCALE, FigureMotion, WALK_SPEED_MPS, clayShader, gait, turn } from './figure'

// Node's fs, loaded at run time so this browser project needs no Node types.
const fs = await import(/* @vite-ignore */ `node:${'fs'}`)
/** The figure file's bytes. */
const BYTES: Uint8Array = new Uint8Array(fs.readFileSync(new URL('./assets/person.glb', import.meta.url)))

/** The JSON chunk of the figure file. */
function glbJson(): any {
  const view = new DataView(BYTES.buffer)
  expect(view.getUint32(0, true)).toBe(0x46546c67) // "glTF"
  const len = view.getUint32(12, true)
  return JSON.parse(new TextDecoder().decode(BYTES.subarray(20, 20 + len)))
}

/** What GLTFLoader's fetch gets: the file, without a body stream (so no progress events, which Node lacks). */
const response = (status: number, bytes = BYTES) => ({
  status,
  ok: status === 200,
  statusText: '',
  headers: new Headers(),
  body: undefined,
  arrayBuffer: async () => bytes.slice().buffer,
})

describe('the figure file', () => {
  const doc = glbJson()

  it('is one small, texture-free skinned mesh within the budget', () => {
    expect(BYTES.length).toBeLessThan(120_000)
    expect(doc.meshes).toHaveLength(1)
    expect(doc.meshes[0].primitives).toHaveLength(1)
    expect(doc.materials ?? []).toHaveLength(1)
    expect(doc.images ?? []).toHaveLength(0)
    expect(doc.textures ?? []).toHaveLength(0)
    const prim = doc.meshes[0].primitives[0]
    expect(doc.accessors[prim.indices].count / 3).toBeLessThanOrEqual(3000)
    expect(Object.keys(prim.attributes).sort()).toEqual(['COLOR_0', 'JOINTS_0', 'NORMAL', 'POSITION', 'WEIGHTS_0'])
    expect(doc.skins[0].joints.length).toBeLessThanOrEqual(20)
  })

  it('stands 1.70 m tall on the origin', () => {
    const pos = doc.accessors[doc.meshes[0].primitives[0].attributes.POSITION]
    expect(pos.min[1]).toBeCloseTo(0, 2)
    expect(pos.max[1]).toBeCloseTo(1.7, 1)
    expect(Math.abs(pos.min[0] + pos.max[0])).toBeLessThan(0.01) // centred left to right
  })

  it('has a walk of about 1.07 s and a calm idle, with the walk speed the code expects', () => {
    const length = (name: string) => {
      const anim = doc.animations.find((a: any) => a.name === name)
      expect(anim).toBeTruthy()
      return Math.max(...anim.samplers.map((s: any) => doc.accessors[s.input].max[0]))
    }
    expect(length('walk')).toBeGreaterThanOrEqual(1.0)
    expect(length('walk')).toBeLessThanOrEqual(1.1)
    expect(length('idle')).toBeCloseTo(8, 1)
    const extras = doc.scenes[doc.scene ?? 0].extras
    expect(extras.walkCycleS).toBeCloseTo(length('walk'), 3)
    expect(extras.walkSpeedMps).toBeCloseTo(extras.strideM / extras.walkCycleS, 6)
    expect(extras.walkSpeedMps).toBeCloseTo(WALK_SPEED_MPS, 4)
  })
})

describe('gait', () => {
  it('plays the walk as made when no speed is given, or at its own speed', () => {
    expect(gait(undefined, 0.8)).toEqual({ stride: 1, rate: 1 })
    expect(gait(Number.NaN, 0.8)).toEqual({ stride: 1, rate: 1 })
    expect(gait(0.8, 0.8)).toEqual({ stride: 1, rate: 1 })
  })

  it('shortens the stride and slows the cadence together, so the feet keep pace with the floor', () => {
    const g = gait(0.4, 0.8)
    expect(g.stride).toBeCloseTo(Math.SQRT1_2)
    expect(g.rate).toBeCloseTo(Math.SQRT1_2)
    expect(g.stride * g.rate).toBeCloseTo(0.5) // stride x cadence = speed
  })

  it('steps faster rather than overstriding above its own speed', () => {
    const g = gait(1.2, 0.8)
    expect(g.stride).toBe(1)
    expect(g.rate).toBeCloseTo(1.5)
  })

  it('clamps at the extremes instead of freezing or racing', () => {
    expect(gait(0, 0.8)).toEqual({ stride: 0.5, rate: 0.55 })
    expect(gait(-1, 0.8)).toEqual({ stride: 0.5, rate: 0.55 })
    expect(gait(10, 0.8).rate).toBe(1.6)
  })
})

describe('figure motion', () => {
  const run = (m: FigureMotion, ms: number, dt = 1000 / 60) => {
    let busy = false
    for (let t = 0; t < ms - 1e-9; t += dt) busy = m.step(Math.min(dt, ms - t))
    return busy
  }

  it('crossfades from standing to walking in CROSSFADE_MS', () => {
    const m = new FigureMotion(0.8)
    m.moving = true
    run(m, CROSSFADE_MS / 2)
    expect(m.walk).toBeCloseTo(0.5, 2)
    run(m, CROSSFADE_MS / 2)
    expect(m.walk).toBe(1)
  })

  it('can turn back midway through a crossfade', () => {
    const m = new FigureMotion(0.8)
    m.moving = true
    run(m, 120)
    m.moving = false
    expect(run(m, 60)).toBe(true)
    expect(m.walk).toBeCloseTo(0.2, 2)
    run(m, 200)
    expect(m.walk).toBe(0)
  })

  it('needs frames while walking or fading, and none once it stands still facing its heading', () => {
    const m = new FigureMotion(0.8)
    expect(m.step(16)).toBe(false)
    m.moving = true
    expect(run(m, 1000)).toBe(true)
    m.moving = false
    expect(run(m, CROSSFADE_MS - 20)).toBe(true)
    expect(run(m, 40)).toBe(false)
    m.headingTo = 2
    expect(m.step(16)).toBe(true)
    expect(run(m, 2000)).toBe(false)
    expect(m.heading).toBe(2)
  })

  it('walks with a shorter stride at a slower floor speed and eases the step rate', () => {
    const m = new FigureMotion(0.8)
    m.moving = true
    m.speed = 0.4
    m.step(16)
    expect(m.rate).toBeGreaterThan(0.95) // the cadence doesn't jump
    run(m, 1500)
    expect(m.walk).toBeCloseTo(Math.SQRT1_2, 3)
    expect(m.rate).toBeCloseTo(Math.SQRT1_2, 2)
  })

  it('turns the short way round', () => {
    expect(turn(0, Math.PI / 2)).toBeCloseTo(Math.PI / 2)
    expect(turn(Math.PI * 0.9, -Math.PI * 0.9)).toBeCloseTo(Math.PI * 0.2)
    const m = new FigureMotion(0.8)
    m.heading = Math.PI * 0.9
    m.headingTo = -Math.PI * 0.9
    m.step(16)
    expect(Math.abs(m.heading)).toBeGreaterThan(Math.PI * 0.9) // went through pi, not back through 0
  })
})

describe('clay shade', () => {
  it('replaces the matcap fallback in the shader three ships', () => {
    const shader = { fragmentShader: ShaderLib.matcap.fragmentShader }
    expect(clayShader(shader)).toBe(true)
    expect(shader.fragmentShader).toContain('figure-shade')
    expect(shader.fragmentShader).not.toContain('mix( 0.2, 0.8, uv.y )')
  })

  it('leaves an unknown shader alone', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const shader = { fragmentShader: 'void main() {}' }
    expect(clayShader(shader)).toBe(false)
    expect(shader.fragmentShader).toBe('void main() {}')
  })
})

describe('createFigure', () => {
  beforeEach(() => {
    vi.resetModules()
    // GLTFLoader fetches the file: hand it the real bytes.
    vi.stubGlobal('Request', class {
      constructor(readonly url: string) {}
    })
    vi.stubGlobal('fetch', async () => response(200))
  })
  afterEach(() => vi.unstubAllGlobals())

  const load = async () => {
    const { createFigure } = await import('./figure')
    let loaded: boolean | null = null
    const fig = createFigure((ok) => (loaded = ok))
    await vi.waitFor(() => expect(loaded).not.toBeNull())
    return { fig, loaded: loaded as boolean | null }
  }
  const skinned = (o: Object3D) => {
    const out: SkinnedMesh[] = []
    o.traverse((c) => c instanceof SkinnedMesh && out.push(c))
    return out
  }
  const bone = (o: Object3D, name: string) => o.getObjectByName(name)!

  it('loads the clay figure at room scale and says so', async () => {
    const { fig, loaded } = await load()
    expect(loaded).toBe(true)
    const [body, twin] = skinned(fig.object)
    expect(body.material).toBeInstanceOf(MeshMatcapMaterial)
    expect((body.material as MeshMatcapMaterial).transparent).toBe(false)
    expect(twin.visible).toBe(false)
    expect(fig.object.children[0].scale.x).toBeCloseTo(FIGURE_SCALE)
  })

  it('draws see-through at 0.35 with a depth pre-pass ordered after the floor', async () => {
    const { fig } = await load()
    fig.setOpacity(0.35)
    const [body, twin] = skinned(fig.object)
    const mat = body.material as MeshMatcapMaterial
    expect(mat.transparent).toBe(true)
    expect(mat.opacity).toBeCloseTo(0.35)
    expect(twin.visible).toBe(true)
    expect(twin.material).toMatchObject({ colorWrite: false, depthWrite: true, transparent: true })
    expect(twin.renderOrder).toBeGreaterThan(0)
    expect(body.renderOrder).toBeGreaterThan(twin.renderOrder)
    expect(twin.skeleton).toBe(body.skeleton)
    fig.setOpacity(1)
    expect((body.material as MeshMatcapMaterial).transparent).toBe(false)
    expect(twin.visible).toBe(false)
  })

  it('walks while moving, and settles into the idle without asking for frames', async () => {
    const { fig } = await load()
    const foot = bone(fig.object, 'footL') // the loader drops the dot from 'foot.L'
    expect(fig.update(16)).toBe(false)
    const standing = foot.quaternion.clone()
    fig.setMoving(true)
    for (let i = 0; i < 40; i++) expect(fig.update(16)).toBe(true)
    expect(foot.quaternion.angleTo(standing)).toBeGreaterThan(0.05)
    fig.setMoving(false)
    let frames = 0
    while (fig.update(16)) frames++
    expect(frames * 16).toBeGreaterThanOrEqual(CROSSFADE_MS - 16)
    expect(frames * 16).toBeLessThanOrEqual(CROSSFADE_MS + 16)
    expect(foot.quaternion.angleTo(standing)).toBeLessThan(0.02)
  })

  it('turns smoothly to a heading and holds it', async () => {
    const { fig } = await load()
    fig.setHeading(Math.PI / 2)
    expect(fig.update(16)).toBe(true)
    expect(fig.object.rotation.y).toBeGreaterThan(0)
    expect(fig.object.rotation.y).toBeLessThan(Math.PI / 2)
    for (let i = 0; i < 200; i++) fig.update(16)
    expect(fig.object.rotation.y).toBeCloseTo(Math.PI / 2)
    expect(fig.update(16)).toBe(false)
  })

  it('falls back to the capsule when the file is missing', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubGlobal('fetch', async () => response(404, new Uint8Array()))
    const { fig, loaded } = await load()
    expect(loaded).toBe(false)
    expect(fig.object.children).toHaveLength(2)
    fig.setOpacity(0.5)
    expect(fig.update(16)).toBe(false)
  })

  it('leaves the scene when disposed', async () => {
    const { fig } = await load()
    const { Group } = await import('three')
    const parent = new Group()
    parent.add(fig.object)
    fig.dispose()
    expect(parent.children).toHaveLength(0)
  })
})
