import { SIZE_M, STRIP_M } from './frame'
import type { Scan, ScanFit } from './scan'

// The hall model's desks (models/hall-desks.json, made from the hall builder's hall.json by
// `npm run scan:desks`), so the desk layout can stand at a real desk: the strip on the seating side of one desk,
// on that desk's tier. Align mode moves it from desk to desk (J L I K) and along a desk (U O); with no
// alignment saved yet, it stands at the default desk.
//
// The hall's desks are arcs around one centre, in the model's own metres (glTF x and z before room.json places
// it): a point of a desk is centre + r * (sin th, cos th), and r grows away from the front, up the tiers.

export interface HallDesk {
  row: number
  wedge: number
  /** Radius of the desk's middle line. */
  r_m: number
  th0_deg: number
  th1_deg: number
  /** Its tier's floor above the hall's front floor. */
  floor_m: number
}

export interface HallDesks {
  centre_m: [number, number]
  desk_depth_m: number
  desks: HallDesk[]
}

/** Where the strip stands: a desk, and how far along it (0 its th0 end, 1 its th1 end) the strip's middle is. */
export interface DeskSpot {
  desk: HallDesk
  along: number
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** The file's desks, or null when it isn't one. */
export function parseDesks(json: unknown): HallDesks | null {
  const j = json as Partial<HallDesks> | null
  if (!j || !Array.isArray(j.centre_m) || !j.centre_m.every(finite) || !finite(j.desk_depth_m) || !Array.isArray(j.desks)) return null
  const desks = j.desks.filter(
    (d): d is HallDesk => !!d && [d.row, d.wedge, d.r_m, d.th0_deg, d.th1_deg, d.floor_m].every(finite) && d.th1_deg > d.th0_deg,
  )
  return desks.length ? { centre_m: [j.centre_m[0], j.centre_m[1]], desk_depth_m: j.desk_depth_m, desks } : null
}

/** "Row 3, block 2": counted from the front and from 1, as people say it. */
export function deskName(d: HallDesk): string {
  return `Row ${d.row + 1}, block ${d.wedge + 1}`
}

/** Until the team's table is known: the third row of the block nearest straight ahead. */
export function defaultSpot(h: HallDesks): DeskSpot {
  const mid = (d: HallDesk) => Math.abs((d.th0_deg + d.th1_deg) / 2)
  const rows = [...new Set(h.desks.map((d) => d.row))].sort((a, b) => a - b)
  const row = rows[Math.min(2, rows.length - 1)]
  const desk = h.desks.filter((d) => d.row === row).sort((a, b) => mid(a) - mid(b))[0]
  return { desk, along: 0.5 }
}

/** The strip's frame in the model at a spot: its middle on the desk's back edge, east along the desk, and the way
 *  up the tiers (layout south). */
function frameAt(h: HallDesks, s: DeskSpot) {
  const th = ((s.desk.th0_deg + (s.desk.th1_deg - s.desk.th0_deg) * s.along) * Math.PI) / 180
  const up: [number, number] = [Math.sin(th), Math.cos(th)]
  const east: [number, number] = [up[1], -up[0]]
  const back = s.desk.r_m + h.desk_depth_m / 2
  const edge: [number, number] = [h.centre_m[0] + back * up[0], h.centre_m[1] + back * up[1]]
  return { up, east, edge }
}

/**
 * The alignment (room.json) that stands the layout at `spot`: the strip's north edge on the desk's back edge, its
 * middle at `along`, east along the desk, on the desk's tier. `box` is the model's own bounding box (x and z), as
 * placeScan centres it.
 */
export function deskFit(h: HallDesks, spot: DeskSpot, box: { min: number[]; max: number[] }, cut_m: number): Required<ScanFit> {
  const [sw, sh] = STRIP_M ?? SIZE_M
  const [fw, fh] = SIZE_M
  const { up, east, edge } = frameAt(h, spot)
  // The layout's origin (the strip's aisle-side west corner) in the model.
  const ox = edge[0] + sh * up[0] - (sw / 2) * east[0]
  const oz = edge[1] + sh * up[1] - (sw / 2) * east[1]
  // Turn so the desk's east lies along the scene's +x (yaw kept to 0.1 degree, as align mode saves it).
  const yaw = Math.round((Math.atan2(east[1], east[0]) * 1800) / Math.PI) / 10
  const p = (yaw * Math.PI) / 180
  const gx = ox - (box.min[0] + box.max[0]) / 2
  const gz = oz - (box.min[2] + box.max[2]) / 2
  const sx = gx * Math.cos(p) + gz * Math.sin(p)
  const sz = -gx * Math.sin(p) + gz * Math.cos(p)
  // The origin must land where the layout puts it in the scene: (-fw / 2, fh / 2).
  const r3 = (v: number) => Math.round(v * 1000) / 1000
  return { offset_m: [r3(-fw / 2 - sx), r3(-(fh / 2 - sz))], yaw_deg: yaw, scale: 1, cut_m, floor_m: spot.desk.floor_m }
}

export type DeskStep = 'north' | 'south' | 'east' | 'west'

/**
 * The next desk spot from `from` in a direction, as the layout sees it. North (toward the front) and south (up the
 * tiers) go to the next row, staying at the same angle around the hall, so a walk up the rows runs straight; a
 * row with a gap there gives its nearest desk. East and west go to the next desk of the same row, at its middle.
 * Null when there is none that way. By row and by angle, not by distance: the desks are of very different
 * lengths, and the nearest one's middle is often in another row.
 */
export function stepDesk(h: HallDesks, from: DeskSpot, dir: DeskStep): DeskSpot | null {
  const th = from.desk.th0_deg + (from.desk.th1_deg - from.desk.th0_deg) * from.along
  const mid = (d: HallDesk) => (d.th0_deg + d.th1_deg) / 2
  if (dir === 'east' || dir === 'west') {
    const sign = dir === 'east' ? 1 : -1
    const next = h.desks
      .filter((d) => d.row === from.desk.row && (mid(d) - mid(from.desk)) * sign > 0)
      .sort((a, b) => (mid(a) - mid(b)) * sign)[0]
    return next ? { desk: next, along: 0.5 } : null
  }
  const sign = dir === 'south' ? 1 : -1
  const row = [...new Set(h.desks.map((d) => d.row))].filter((r) => (r - from.desk.row) * sign > 0).sort((a, b) => (a - b) * sign)[0]
  if (row === undefined) return null
  const gap = (d: HallDesk) => Math.max(d.th0_deg - th, th - d.th1_deg, 0)
  const desk = h.desks.filter((d) => d.row === row).sort((a, b) => gap(a) - gap(b))[0]
  return { desk, along: clampAlong(desk, (th - desk.th0_deg) / (desk.th1_deg - desk.th0_deg)) }
}

/** How far along a desk the strip's middle may sit: half a strip in from either end. */
function clampAlong(desk: HallDesk, along: number, stripM = (STRIP_M ?? SIZE_M)[0]): number {
  const length = (((desk.th1_deg - desk.th0_deg) * Math.PI) / 180) * desk.r_m
  if (length <= stripM) return 0.5
  const lo = stripM / 2 / length
  return Math.min(1 - lo, Math.max(lo, along))
}

/** The same desk, the strip's middle moved `metres` east along it (th grows eastward); never past either end. */
export function slideDesk(from: DeskSpot, metres: number): DeskSpot {
  const { desk } = from
  const length = (((desk.th1_deg - desk.th0_deg) * Math.PI) / 180) * desk.r_m
  return { desk, along: clampAlong(desk, from.along + metres / length) }
}

/** A point of the scene's floor (x, z) in the model's own metres, undoing the alignment `fit` (placeScan). */
export function modelPoint(scene: [number, number], fit: ScanFit, box: { min: number[]; max: number[] }): [number, number] {
  const [dx, dy] = fit.offset_m ?? [0, 0]
  const p = ((fit.yaw_deg ?? 0) * Math.PI) / 180
  const scale = fit.scale && fit.scale > 0 ? fit.scale : 1
  const vx = (scene[0] - dx) / scale
  const vz = (scene[1] + dy) / scale
  return [vx * Math.cos(p) - vz * Math.sin(p) + (box.min[0] + box.max[0]) / 2, vx * Math.sin(p) + vz * Math.cos(p) + (box.min[2] + box.max[2]) / 2]
}

/** The desk spot nearest a point of the model (where the strip's desk edge is now), for snapping to it. */
export function nearestSpot(h: HallDesks, [x, z]: [number, number]): DeskSpot {
  const th = (Math.atan2(x - h.centre_m[0], z - h.centre_m[1]) * 180) / Math.PI
  let best: DeskSpot = { desk: h.desks[0], along: 0.5 }
  let bestD = Infinity
  for (const desk of h.desks) {
    const along = clampAlong(desk, (th - desk.th0_deg) / (desk.th1_deg - desk.th0_deg))
    const at = ((desk.th0_deg + (desk.th1_deg - desk.th0_deg) * along) * Math.PI) / 180
    const back = desk.r_m + h.desk_depth_m / 2
    const d = Math.hypot(h.centre_m[0] + back * Math.sin(at) - x, h.centre_m[1] + back * Math.cos(at) - z)
    if (d < bestD) {
      best = { desk, along }
      bestD = d
    }
  }
  return best
}

/** The hall's desks, when the build has them (models/hall-desks.json); else null. */
export async function loadDesks(url = 'models/hall-desks.json'): Promise<HallDesks | null> {
  try {
    const res = await fetch(url, { cache: 'no-store', signal: AbortSignal.timeout(2000) })
    return res.ok ? parseDesks(await res.json()) : null
  } catch {
    return null
  }
}

/** A hall's walls are kept whole when nothing says where to cut them (a room scan's default is 1.4 m). */
const HALL_CUT_M = 12

/** On the desk layout, a hall with no alignment saved yet stands the strip at the default desk, so the first look
 *  is already a person at a real desk. A saved alignment (room.json, or the board's) is never touched. */
export async function standAtDefaultDesk(scan: Scan | null): Promise<Scan | null> {
  if (!scan || !STRIP_M || scan.fit.offset_m) return scan
  const hall = await loadDesks()
  if (hall) scan.apply(deskFit(hall, defaultSpot(hall), scan.box, scan.fit.cut_m ?? HALL_CUT_M))
  return scan
}
