// Room geometry from CONTRACTS.md v2 section 3: everything comes from radio/nodes.json (applyLayout).
// Contract frame: metres, origin at the layout's south-west corner, x east, y north, z up.
// Scene frame (three.js): y up, the layout's rectangle centred on the origin, north towards -z.
//
// Two layouts read the same way: the 2 x 2 m square (four zones in quarters) and the desk (a 1.6 x 0.6 m strip in
// front of a desk, split into two zones at zone_split_x_m). The built-in values below are the square, used only
// when /nodes.json can't be read.

export type Vec3 = [number, number, number]
export type NodeId = string

/** The whole layout from the origin, [east, north] metres: the square, or the strip plus the desk behind it. */
export let SIZE_M: [number, number] = [2.0, 2.0]
/** The strip a person stands in, [east, north] from the origin, or null on the square (the whole square). */
export let STRIP_M: [number, number] | null = null
/** Where the strip's two zones meet (x, metres), or null on the square. */
export let ZONE_SPLIT_X_M: number | null = null

export interface NodeInfo {
  id: NodeId
  xyz: Vec3
  /** What the screen calls it: nodes.json's name, or a plain default for the square's four nodes. */
  name: string
  roles: string[]
}

/** Plain names for nodes.json files that don't give one (the square's file). */
const DEFAULT_NAMES: Record<string, string> = { unoq: 'UNO Q', pi5: 'Pi 5 router', east: 'East beacon', west: 'West beacon' }

export const NODES: Record<NodeId, NodeInfo> = {
  unoq: { id: 'unoq', xyz: [1.0, 2.0, 1.0], name: 'UNO Q', roles: ['receiver'] },
  pi5: { id: 'pi5', xyz: [1.0, 0.0, 1.0], name: 'Pi 5 router', roles: ['router', 'beacon', 'receiver'] },
  east: { id: 'east', xyz: [2.0, 1.0, 1.0], name: 'East beacon', roles: ['beacon'] },
  west: { id: 'west', xyz: [0.0, 1.0, 1.0], name: 'West beacon', roles: ['beacon'] },
}

export const LINK_IDS: string[] = ['pi5>unoq:wifi', 'pi5>unoq:ble', 'east>unoq:ble', 'west>unoq:ble', 'east>pi5:ble', 'west>pi5:ble']

export interface ZoneInfo {
  id: number
  name: string
  /** nodes.json's centre_m, when it gives one. */
  centre: [number, number] | null
}

export const ZONES: ZoneInfo[] = [
  { id: 1, name: 'Bed', centre: null },
  { id: 2, name: 'Chair', centre: null },
  { id: 3, name: 'Hall', centre: null },
  { id: 4, name: 'Bathroom', centre: null },
]

export const ROUTER_SPOTS: Record<string, Vec3> = {
  'S-home': [1.0, 0.0, 1.0],
  'S-W30': [0.7, 0.0, 1.0],
  'S-E30': [1.3, 0.0, 1.0],
}

export const HOME_SPOT = 'S-home'

/** Where the tray goes for the object test: nodes.json's tray_spots, in order. */
export const TRAY_SPOTS: Vec3[] = [[1.0, 0.2, 1.0]]

/** A beacon far outside the layout (nodes.json hall.beacons): its node id, its letter, and where it is in the
 *  layout's frame, or null until someone places it. */
export interface HallBeacon {
  node: string
  id: string
  xyz: Vec3 | null
}

/** nodes.json's optional hall beacons; empty when the file has none. */
export const HALL_BEACONS: HallBeacon[] = []

export interface LinkParts {
  tx: NodeId
  rx: NodeId
  kind: string
}

/** The node that routes (roles include "router"): it follows state.router between the router spots. */
export function routerId(): NodeId {
  return Object.values(NODES).find((n) => n.roles.includes('router'))?.id ?? 'pi5'
}

/** "<tx>><rx>:<kind>" -> parts, or null when the id doesn't name two nodes in the layout. */
export function parseLinkId(id: string): LinkParts | null {
  const m = /^([a-z0-9]+)>([a-z0-9]+):([a-z0-9]+)$/.exec(id)
  if (!m || !(m[1] in NODES) || !(m[2] in NODES)) return null
  return { tx: m[1], rx: m[2], kind: m[3] }
}

/** Contract point (x east, y north, z up) -> scene point (x, y up, z south), the layout centred on the origin. */
export function toScene([x, y, z]: Vec3): Vec3 {
  return [x - SIZE_M[0] / 2, z, SIZE_M[1] / 2 - y]
}

/** The floor a person can be in: the strip, or the whole square. [east, north] metres from the origin. */
export function floorSize(): [number, number] {
  return STRIP_M ?? SIZE_M
}

/**
 * Zone id from a contract floor point, 0 when it is outside every zone.
 * Strip: 1 + (x >= split) inside the strip. Square: 1 + (x >= half) + 2 * (y < half).
 */
export function zoneAt(x: number, y: number): number {
  if (STRIP_M && ZONE_SPLIT_X_M !== null) {
    if (x < 0 || x > STRIP_M[0] || y < 0 || y > STRIP_M[1]) return 0
    return 1 + (x >= ZONE_SPLIT_X_M ? 1 : 0)
  }
  return 1 + (x >= SIZE_M[0] / 2 ? 1 : 0) + 2 * (y < SIZE_M[1] / 2 ? 1 : 0)
}

/** A zone's floor rectangle [x0, y0, x1, y1] in contract metres, or null for 0 and unknown ids. */
export function zoneRect(zone: number): [number, number, number, number] | null {
  if (!ZONES.some((z) => z.id === zone)) return null
  if (STRIP_M && ZONE_SPLIT_X_M !== null) {
    const [w, h] = STRIP_M
    return zone === 1 ? [0, 0, ZONE_SPLIT_X_M, h] : [ZONE_SPLIT_X_M, 0, w, h]
  }
  const [w, h] = SIZE_M
  const east = zone === 2 || zone === 4
  const south = zone === 3 || zone === 4
  return [east ? w / 2 : 0, south ? 0 : h / 2, east ? w : w / 2, south ? h / 2 : h]
}

/** Centre of a zone in contract metres (nodes.json's centre_m, else the middle of its rectangle), or null. */
export function zoneCenter(zone: number): [number, number] | null {
  const info = ZONES.find((z) => z.id === zone)
  if (info?.centre) return info.centre
  const r = zoneRect(zone)
  return r ? [(r[0] + r[2]) / 2, (r[1] + r[3]) / 2] : null
}

/** Which way a zone faces out: east or west of the layout's middle, north or south of it. */
export function zoneSide(zone: number): { east: boolean; north: boolean } {
  const [x, y] = zoneCenter(zone) ?? [0, 0]
  return { east: x > SIZE_M[0] / 2, north: y > SIZE_M[1] / 2 }
}

export type LabelSide = 'above' | 'above-left' | 'above-right' | 'right' | 'left' | 'below-right' | 'below-left'

/** Which side of its head a node's name goes. On the square: outward at the east and west edges, above at the
 *  north edge (the UNO Q), else to the right. On the desk the names take no room beside the strip: a device on the
 *  desk has its name above it, and a beacon out over the aisle has it just below, reading inward from its stand
 *  (every link from it runs up toward the desk, and its stand runs down). */
/** Devices nearer than this share the room above them: their names would overlap. */
const CLOSE_M = 0.25

export function nodeLabelSide(id: NodeId): LabelSide {
  const [x, y] = NODES[id]?.xyz ?? [0, 0, 0]
  if (STRIP_M) {
    if (y < STRIP_M[1] - 0.01) return x < SIZE_M[0] / 2 ? 'below-right' : 'below-left'
    // Two devices side by side on the desk (the board and the router on one hub): their names read outward from
    // each other instead of landing on one another.
    const beside = Object.values(NODES).find((n) => n.id !== id && Math.abs(n.xyz[1] - y) < CLOSE_M && Math.abs(n.xyz[0] - x) < CLOSE_M)
    return !beside ? 'above' : x < beside.xyz[0] || (x === beside.xyz[0] && id < beside.id) ? 'above-left' : 'above-right'
  }
  if (x <= 0.05) return 'left'
  if (x >= SIZE_M[0] - 0.05) return 'right'
  return y >= SIZE_M[1] - 0.05 ? 'above' : 'right'
}

/** Where a zone's no-movement word goes, and which way it reads from that point. On the square: on the floor just
 *  outside it, level with the zone's name, on the zone's own side (east zones to the east, west zones to the
 *  west). On the desk: in the aisle just in front of its zone, under its middle ('south'), where it takes no
 *  room beside the strip. */
export function alertWordAt(zone: number): [Vec3, 'west' | 'east' | 'south'] {
  const [x0, y0, x1, y1] = zoneRect(zone) ?? [0, 0, 0, 0]
  if (STRIP_M) return [[(x0 + x1) / 2, -0.06, 0], 'south']
  const { east, north } = zoneSide(zone)
  return [[east ? floorSize()[0] + 0.08 : -0.08, north ? y1 - 0.2 : y0 + 0.2, 0], east ? 'east' : 'west']
}

/** Where a node sits now. The router follows state.router to its spot. */
export function nodePosition(id: NodeId, router: string | null | undefined): Vec3 {
  if (id === routerId() && router && ROUTER_SPOTS[router]) return ROUTER_SPOTS[router]
  return NODES[id]?.xyz ?? [0, 0, 0]
}

type Json = Record<string, unknown>

function isVec3(v: unknown): v is Vec3 {
  return Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === 'number' && Number.isFinite(n))
}

function isPair(v: unknown, lo: number, hi: number): v is [number, number] {
  return Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === 'number' && n >= lo && n <= hi)
}

/** Every value in place: the exported bindings are read live by the rest of the room. */
function replace<T>(target: T[], items: T[]) {
  target.splice(0, target.length, ...items)
}

/**
 * Applies radio/nodes.json (contract section 3): the layout's size and strip, nodes (positions, names, roles),
 * links, zones, router spots and tray spots. All or nothing: returns false and changes nothing when the file
 * doesn't look like the contract.
 */
export function applyLayout(json: unknown): boolean {
  const j = json as Json | null
  if (!j || j.v !== 2 || !Array.isArray(j.nodes)) return false
  const frame = (j.frame ?? {}) as Json
  if (!isPair(frame.size_m, 0.5, 10)) return false
  const size = frame.size_m
  const strip = frame.strip_m === undefined || frame.strip_m === null ? null : frame.strip_m
  if (strip !== null && !isPair(strip, 0.1, 10)) return false
  const split = typeof frame.zone_split_x_m === 'number' ? frame.zone_split_x_m : null
  if (strip && (split === null || split <= 0 || split >= strip[0])) return false

  const nodes: NodeInfo[] = []
  for (const n of j.nodes as Json[]) {
    if (typeof n?.id !== 'string' || !/^[a-z0-9]+$/.test(n.id) || !isVec3(n.xyz_m)) return false
    const roles = Array.isArray(n.roles) ? n.roles.filter((r): r is string => typeof r === 'string') : []
    const name = typeof n.name === 'string' && n.name.trim() ? n.name.trim() : (DEFAULT_NAMES[n.id] ?? n.id)
    nodes.push({ id: n.id, xyz: n.xyz_m, name, roles })
  }
  if (nodes.length < 2 || new Set(nodes.map((n) => n.id)).size !== nodes.length) return false
  const ids = new Set(nodes.map((n) => n.id))

  const links: string[] = []
  for (const l of Array.isArray(j.links) ? (j.links as Json[]) : []) {
    const m = typeof l?.id === 'string' ? /^([a-z0-9]+)>([a-z0-9]+):([a-z0-9]+)$/.exec(l.id) : null
    if (!m || !ids.has(m[1]) || !ids.has(m[2])) return false
    links.push(l.id as string)
  }
  if (!links.length) return false

  const zones: ZoneInfo[] = []
  for (const z of Array.isArray(j.zones) ? (j.zones as Json[]) : []) {
    if (typeof z?.id !== 'number' || typeof z.name !== 'string' || !z.name.trim()) return false
    const c = z.centre_m
    zones.push({ id: z.id, name: z.name.trim(), centre: isPair(c, -10, 10) ? c : null })
  }
  if (zones.length !== (strip ? 2 : 4)) return false

  const spots = (Array.isArray(j.router_spots) ? (j.router_spots as Json[]) : []).filter(
    (r): r is { id: string; xyz_m: Vec3 } => typeof r?.id === 'string' && isVec3(r.xyz_m),
  )
  const trays = (Array.isArray(j.tray_spots) ? (j.tray_spots as Json[]) : []).map((t) => t?.xyz_m).filter(isVec3)
  // Optional, and never a reason to refuse the file: a malformed beacon is left out.
  const hallList = ((j.hall as Json | undefined)?.beacons ?? []) as Json[]
  const hall: HallBeacon[] = (Array.isArray(hallList) ? hallList : [])
    .filter((b) => typeof b?.node === 'string' && /^[a-z0-9]+$/.test(b.node) && !ids.has(b.node))
    .map((b) => ({ node: b.node as string, id: typeof b.id === 'string' ? b.id : (b.node as string).toUpperCase(), xyz: isVec3(b.xyz_m) ? b.xyz_m : null }))

  SIZE_M = [size[0], size[1]]
  STRIP_M = strip ? [strip[0], strip[1]] : null
  ZONE_SPLIT_X_M = strip ? split : null
  for (const k of Object.keys(NODES)) delete NODES[k]
  for (const n of nodes) NODES[n.id] = n
  replace(LINK_IDS, links)
  replace(ZONES, zones.sort((a, b) => a.id - b.id))
  if (spots.some((r) => r.id === HOME_SPOT)) {
    for (const k of Object.keys(ROUTER_SPOTS)) delete ROUTER_SPOTS[k]
    for (const r of spots) ROUTER_SPOTS[r.id] = r.xyz_m
  }
  if (trays.length) replace(TRAY_SPOTS, trays)
  // The router's spots and the tray's are places around the router. When the file puts the router somewhere
  // else than S-home (a placement saved in align mode moves the devices, not the spots), they travel with it, so
  // S-home is always where the router is.
  const router = nodes.find((n) => n.roles.includes('router'))
  const home = ROUTER_SPOTS[HOME_SPOT]
  if (router && home) {
    const d = router.xyz.map((v, i) => v - home[i])
    if (d.some((v) => Math.abs(v) > 1e-6)) {
      const moved = (p: Vec3): Vec3 => [p[0] + d[0], p[1] + d[1], p[2] + d[2]]
      for (const k of Object.keys(ROUTER_SPOTS)) ROUTER_SPOTS[k] = moved(ROUTER_SPOTS[k])
      replace(TRAY_SPOTS, TRAY_SPOTS.map(moved))
    }
  }
  replace(HALL_BEACONS, hall)
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
