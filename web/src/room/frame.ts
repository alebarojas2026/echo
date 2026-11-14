// Room geometry from CONTRACTS.md v2 section 3.
// Contract frame: metres, origin at the square's south-west corner, x east, y north, z up.
// Scene frame (three.js): y up, the square centred on the origin, north towards -z.

export type Vec3 = [number, number, number]
export type NodeId = 'unoq' | 'pi5' | 'east' | 'west'

/** The square's side. Replaced by radio/nodes.json at start-up (applyLayout); read it, never copy it. */
export let SQUARE_M = 2.0

export interface NodeInfo {
  id: NodeId
  xyz: Vec3
  name: string
  role: string
}

export const NODES: Record<NodeId, NodeInfo> = {
  unoq: { id: 'unoq', xyz: [1.0, 2.0, 1.0], name: 'UNO Q', role: 'receiver' },
  pi5: { id: 'pi5', xyz: [1.0, 0.0, 1.0], name: 'Pi 5', role: 'router' },
  east: { id: 'east', xyz: [2.0, 1.0, 1.0], name: 'East', role: 'beacon' },
  west: { id: 'west', xyz: [0.0, 1.0, 1.0], name: 'West', role: 'beacon' },
}

export const LINK_IDS = [
  'pi5>unoq:wifi',
  'pi5>unoq:ble',
  'east>unoq:ble',
  'west>unoq:ble',
  'east>pi5:ble',
  'west>pi5:ble',
] as const

export interface ZoneInfo {
  id: number
  name: string
  corner: string
}

export const ZONES: ZoneInfo[] = [
  { id: 1, name: 'Bed', corner: 'NW' },
  { id: 2, name: 'Chair', corner: 'NE' },
  { id: 3, name: 'Hall', corner: 'SW' },
  { id: 4, name: 'Bathroom', corner: 'SE' },
]

export const ROUTER_SPOTS: Record<string, Vec3> = {
  'S-home': [1.0, 0.0, 1.0],
  'S-W30': [0.7, 0.0, 1.0],
  'S-E30': [1.3, 0.0, 1.0],
}

export const HOME_SPOT = 'S-home'

export interface LinkParts {
  tx: NodeId
  rx: NodeId
  kind: string
}

const NODE_IDS = new Set<string>(Object.keys(NODES))

/** "<tx>><rx>:<kind>" -> parts, or null when the id doesn't name two known nodes. */
export function parseLinkId(id: string): LinkParts | null {
  const m = /^([a-z0-9]+)>([a-z0-9]+):([a-z0-9]+)$/.exec(id)
  if (!m || !NODE_IDS.has(m[1]) || !NODE_IDS.has(m[2])) return null
  return { tx: m[1] as NodeId, rx: m[2] as NodeId, kind: m[3] }
}

/** Contract point (x east, y north, z up) -> scene point (x, y up, z south). */
export function toScene([x, y, z]: Vec3): Vec3 {
  const half = SQUARE_M / 2
  return [x - half, z, half - y]
}

/** Zone id from a contract floor point: zone = 1 + (x >= 1) + 2*(y < 1). */
export function zoneAt(x: number, y: number): number {
  const half = SQUARE_M / 2
  return 1 + (x >= half ? 1 : 0) + 2 * (y < half ? 1 : 0)
}

/** Centre of a zone (1-4) in contract metres, or null for 0 and unknown ids. */
export function zoneCenter(zone: number): [number, number] | null {
  if (zone < 1 || zone > 4) return null
  const q = SQUARE_M / 4
  const east = zone === 2 || zone === 4
  const south = zone === 3 || zone === 4
  return [east ? 3 * q : q, south ? q : 3 * q]
}

/** Where a node sits now. The router (pi5) follows state.router to its spot. */
export function nodePosition(id: NodeId, router: string | null | undefined): Vec3 {
  if (id === 'pi5' && router && ROUTER_SPOTS[router]) return ROUTER_SPOTS[router]
  return NODES[id].xyz
}

type Json = Record<string, unknown>

function isVec3(v: unknown): v is Vec3 {
  return Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === 'number' && Number.isFinite(n))
}

/**
 * Applies radio/nodes.json (contract section 3): square size, node positions, router spots and zone names.
 * All or nothing: returns false and changes nothing when the file doesn't look like the contract.
 */
export function applyLayout(json: unknown): boolean {
  const j = json as Json | null
  if (!j || j.v !== 2 || !Array.isArray(j.nodes)) return false
  const sizeM = (j.frame as Json | undefined)?.size_m
  const size = Array.isArray(sizeM) ? Number(sizeM[0]) : NaN
  if (!(size >= 0.5 && size <= 10)) return false

  const nodes = new Map<NodeId, Vec3>()
  for (const n of j.nodes as Json[]) {
    if (typeof n?.id === 'string' && n.id in NODES && isVec3(n.xyz_m)) nodes.set(n.id as NodeId, n.xyz_m)
  }
  if (nodes.size !== Object.keys(NODES).length) return false

  const spots = (Array.isArray(j.router_spots) ? (j.router_spots as Json[]) : []).filter(
    (r): r is { id: string; xyz_m: Vec3 } => typeof r?.id === 'string' && isVec3(r.xyz_m),
  )
  const zoneNames = new Map<number, string>()
  for (const z of Array.isArray(j.zones) ? (j.zones as Json[]) : []) {
    if (typeof z?.id === 'number' && typeof z.name === 'string' && z.name.trim()) zoneNames.set(z.id, z.name.trim())
  }

  SQUARE_M = size
  for (const [id, xyz] of nodes) NODES[id].xyz = xyz
  if (spots.some((r) => r.id === HOME_SPOT)) {
    for (const k of Object.keys(ROUTER_SPOTS)) delete ROUTER_SPOTS[k]
    for (const r of spots) ROUTER_SPOTS[r.id] = r.xyz_m
  }
  for (const z of ZONES) z.name = zoneNames.get(z.id) ?? z.name
  return true
}

/** A short floor tag for a router spot: "home", or how far and which way it is from home ("30 cm W"). */
export function spotName(id: string): string {
  const home = ROUTER_SPOTS[HOME_SPOT]
  const spot = ROUTER_SPOTS[id]
  if (!home || !spot || id === HOME_SPOT) return id === HOME_SPOT ? 'home' : id
  const dx = spot[0] - home[0]
  const dy = spot[1] - home[1]
  const cm = Math.round(Math.hypot(dx, dy) * 100)
  const dir = Math.abs(dx) >= Math.abs(dy) ? (dx < 0 ? 'W' : 'E') : dy < 0 ? 'S' : 'N'
  return `${cm} cm ${dir}`
}
