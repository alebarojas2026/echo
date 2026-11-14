// Turns a room scan export (.glb) into web/public/models/room.glb for the screen.
//   npm run scan:prep -- <export.glb> [--max 100000] [--out <file>]
// It strips every texture, vertex colour and UV set (no pictures of the room end up in the repo), welds,
// simplifies to the Pi's triangle budget and compresses with meshopt. The screen draws it flat anyway.
import { mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { NodeIO } from '@gltf-transform/core'
import { ALL_EXTENSIONS } from '@gltf-transform/extensions'
import { dedup, meshopt, prune, simplify, weld } from '@gltf-transform/functions'
import { MeshoptEncoder, MeshoptSimplifier } from 'meshoptimizer'

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { max: { type: 'string', default: '100000' }, out: { type: 'string' } },
})
const input = positionals[0]
if (!input) {
  console.error('usage: npm run scan:prep -- <export.glb> [--max 100000] [--out <file>]')
  process.exit(2)
}
const out = values.out ?? fileURLToPath(new URL('../../../public/models/room.glb', import.meta.url))
const max = Number(values.max)

const triangles = (doc) => {
  let n = 0
  for (const mesh of doc.getRoot().listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const idx = prim.getIndices()
      n += (idx ? idx.getCount() : prim.getAttribute('POSITION').getCount()) / 3
    }
  }
  return Math.round(n)
}

await MeshoptEncoder.ready
await MeshoptSimplifier.ready
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.encoder': MeshoptEncoder })
const doc = await io.read(input)
const before = triangles(doc)

const textures = doc.getRoot().listTextures()
for (const t of textures) t.dispose()
let stripped = 0
for (const mesh of doc.getRoot().listMeshes()) {
  for (const prim of mesh.listPrimitives()) {
    for (const name of prim.listSemantics()) {
      if (name.startsWith('COLOR_') || name.startsWith('TEXCOORD_')) {
        prim.setAttribute(name, null)
        stripped++
      }
    }
  }
}

await doc.transform(weld(), dedup())
if (triangles(doc) > max) {
  await doc.transform(simplify({ simplifier: MeshoptSimplifier, ratio: max / triangles(doc), error: 0.02 }))
}
await doc.transform(prune(), meshopt({ encoder: MeshoptEncoder, level: 'medium' }))
const after = triangles(doc)

await mkdir(dirname(out), { recursive: true })
await io.write(out, doc)
console.log(`${input} -> ${out}`)
console.log(`triangles ${before} -> ${after} (budget ${max}); removed ${textures.length} textures and ${stripped} colour/UV sets`)
console.log('web/public/models/*.glb is git-ignored: the scan reaches the board inside web/dist, not through git.')
if (after > max) console.warn('still over budget: run again with a lower --max')
