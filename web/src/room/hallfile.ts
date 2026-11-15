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
