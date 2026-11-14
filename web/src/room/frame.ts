// Room geometry from CONTRACTS.md v2 section 3.
// Contract frame: metres, origin at the square's south-west corner, x east, y north, z up.
// Scene frame (three.js): y up, the square centred on the origin, north towards -z.

export type Vec3 = [number, number, number]
export type NodeId = 'unoq' | 'pi5' | 'east' | 'west'

export const SQUARE_M = 2.0

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
