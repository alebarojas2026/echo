// Saving hall beacon positions back into radio/nodes.json without reformatting it: only each beacon's xyz_m
// value changes, in place, so the file's diff is one line per beacon moved. Used by the dev server (vite.config.ts)
// for align mode's S.

export type Vec3 = [number, number, number]

/** The file's text with each listed hall beacon's xyz_m replaced; beacons not in the file are left out. */
export function setHallBeaconPositions(text: string, positions: { node: string; xyz_m: Vec3 | null }[]): string {
  let out = text
  for (const { node, xyz_m } of positions) {
    const value = xyz_m ? `[${xyz_m.map((v) => Number(v.toFixed(3))).join(', ')}]` : 'null'
    // One beacon object on its own: {"node": "h", ..., "xyz_m": null}. Only objects with an xyz_m match, so the
    // beacons.payloads entries (which have none) are never touched.
    const re = new RegExp(`(\\{[^{}]*"node":\\s*"${node}"[^{}]*"xyz_m":\\s*)(null|\\[[^\\]]*\\])`)
    out = out.replace(re, (_, head: string) => `${head}${value}`)
  }
  return out
}

/** Only well-formed positions: a known-looking node id and three finite numbers (or null), or null for the lot. */
export function cleanPositions(body: unknown): { node: string; xyz_m: Vec3 | null }[] | null {
  if (!Array.isArray(body)) return null
  const out: { node: string; xyz_m: Vec3 | null }[] = []
  for (const p of body) {
    const node = (p as { node?: unknown })?.node
    const xyz = (p as { xyz_m?: unknown })?.xyz_m
    if (typeof node !== 'string' || !/^[a-z0-9]+$/.test(node)) return null
    const ok = xyz === null || (Array.isArray(xyz) && xyz.length === 3 && xyz.every((v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) < 500))
    if (!ok) return null
    out.push({ node, xyz_m: xyz as Vec3 | null })
  }
  return out
}

const escapeRe = (text: string) => text.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&')
const numbers = (xyz: Vec3) => `[${xyz.map((v) => Number(v.toFixed(3))).join(', ')}]`

/** Replaces the xyz_m of the one object in the file with this "id" (a node, a router spot or a tray spot). */
function setXyz(text: string, id: string, xyz: Vec3): string {
  const re = new RegExp(`(\\{[^{}]*"id":\\s*"${escapeRe(id)}"[^{}]*"xyz_m":\\s*)\\[[^\\]]*\\]`)
  return text.replace(re, (_, head: string) => `${head}${numbers(xyz)}`)
}

/**
 * The file's text with each listed device's xyz_m replaced (align mode's placement, saved with S), one line per
 * device moved. When the router moves, its spots and the tray's move by the same amount, so the file stays one
 * picture: S-home is where the router is. Devices not in the file are left out.
 */
export function setNodePositions(text: string, positions: { id: string; xyz_m: Vec3 }[]): string {
  type Entry = { id?: string; xyz_m?: Vec3; roles?: string[] }
  const file = JSON.parse(text) as { nodes?: Entry[]; router_spots?: Entry[]; tray_spots?: Entry[] }
  let out = text
  for (const { id, xyz_m } of positions) {
    const node = file.nodes?.find((n) => n.id === id)
    if (!node?.xyz_m) continue
    out = setXyz(out, id, xyz_m)
    if (!node.roles?.includes('router')) continue
    const d = xyz_m.map((v, i) => v - node.xyz_m![i])
    for (const spot of [...(file.router_spots ?? []), ...(file.tray_spots ?? [])]) {
      if (spot.id && spot.xyz_m) out = setXyz(out, spot.id, spot.xyz_m.map((v, i) => v + d[i]) as Vec3)
    }
  }
  return out
}

/** Only well-formed device positions: [{id, xyz_m}] with a plain id and three finite numbers, or null for the lot. */
export function cleanNodePositions(body: unknown): { id: string; xyz_m: Vec3 }[] | null {
  if (!Array.isArray(body) || body.length > 16) return null
  const out: { id: string; xyz_m: Vec3 }[] = []
  for (const p of body) {
    const id = (p as { id?: unknown })?.id
    const xyz = (p as { xyz_m?: unknown })?.xyz_m
    if (typeof id !== 'string' || !/^[a-z0-9]+$/.test(id)) return null
    if (!Array.isArray(xyz) || xyz.length !== 3 || !xyz.every((v) => typeof v === 'number' && Number.isFinite(v) && Math.abs(v) <= 5)) return null
    if (xyz[2] < 0 || xyz[2] > 3) return null
    out.push({ id, xyz_m: xyz as Vec3 })
  }
  return out
}
