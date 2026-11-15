import { SIZE_M, STRIP_M, deskEdge, deviceAcross } from './frame'
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
  /** A desk top above its own tier's floor. */
  desk_height_m: number
  desks: HallDesk[]
}

/**
 * Which side of our desk the standing spot (the gap) is on. We don't know until the day where judges will stand:
 *   behind  the seating side, between our desk and the row up the tiers
 *   front   the side toward the front of the hall, between our desk and the row below
 *   end     past the desk's end, in the aisle (the end nearer to `along`)
 * The layout's north is always toward our desk, so the picture turns with the choice.
 */
export type Gap = 'behind' | 'front' | 'end'
export const GAPS: readonly Gap[] = ['behind', 'front', 'end']
export const GAP_WORDS: Record<Gap, string> = { behind: 'gap behind our desk', front: 'gap in front of our desk', end: 'gap at the row end' }

/** Where the strip stands: a desk, how far along it (0 its th0 end, 1 its th1 end) the strip's middle is, and
 *  which side of it the gap is on (behind when not said). */
export interface DeskSpot {
  desk: HallDesk
  along: number
  gap?: Gap
  /** The board and the router stand on the facing desk, and the other devices on ours. Which desk is "ours" is
   *  only known on the day (the first night the board sat on the far table). */
  boardAcross?: boolean
}

/** The height used for a desks file from before it carried one. */
const DESK_HEIGHT_M = 0.75

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** The file's desks, or null when it isn't one. */
export function parseDesks(json: unknown): HallDesks | null {
  const j = json as Partial<HallDesks> | null
  if (!j || !Array.isArray(j.centre_m) || !j.centre_m.every(finite) || !finite(j.desk_depth_m) || !Array.isArray(j.desks)) return null
  const desks = j.desks.filter(
    (d): d is HallDesk => !!d && [d.row, d.wedge, d.r_m, d.th0_deg, d.th1_deg, d.floor_m].every(finite) && d.th1_deg > d.th0_deg,
  )
  if (!desks.length) return null
  const height = finite(j.desk_height_m) && j.desk_height_m > 0 ? j.desk_height_m : DESK_HEIGHT_M
  return { centre_m: [j.centre_m[0], j.centre_m[1]], desk_depth_m: j.desk_depth_m, desk_height_m: height, desks }
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
  // With a device across the spot (the gate, about 1 m deep) the default is the desk's end: the stair aisle has
  // the room for it, where the gap between two rows does not, so nothing is ever drawn inside the next desk.
  return deviceAcross() ? { desk, along: 0.5, gap: 'end' } : { desk, along: 0.5 }
}

const rad = (deg: number) => (deg * Math.PI) / 180
/** A point of the hall in the model: `r` metres from the centre at angle `th` (radians). */
const polar = (h: HallDesks, r: number, th: number): [number, number] => [h.centre_m[0] + r * Math.sin(th), h.centre_m[1] + r * Math.cos(th)]
/** How far (degrees) an angle is outside a desk's span; 0 inside it. */
const outside = (d: HallDesk, thDeg: number) => Math.max(d.th0_deg - thDeg, thDeg - d.th1_deg, 0)

/** The desk of `row` nearest an angle, or undefined when the row has none. */
function deskIn(h: HallDesks, row: number, thDeg: number): HallDesk | undefined {
  return h.desks.filter((d) => d.row === row).sort((a, b) => outside(a, thDeg) - outside(b, thDeg))[0]
}

/** The angle (degrees) of a spot along its desk, and whether an `end` spot is at the desk's east (th1) end. */
function spotAngle(s: DeskSpot): { thDeg: number; eastEnd: boolean } {
  const eastEnd = s.along >= 0.5
  if (s.gap === 'end') return { thDeg: eastEnd ? s.desk.th1_deg : s.desk.th0_deg, eastEnd }
  return { thDeg: s.desk.th0_deg + (s.desk.th1_deg - s.desk.th0_deg) * s.along, eastEnd }
}

/**
 * The layout's frame in the model at a spot: `edge` is the middle of the strip's desk-side edge (on our desk's
 * edge), `north` the unit vector from the gap toward our desk, `east` the layout's east, and `floor_m` the floor
 * the person stands on.
 */
function frameAt(h: HallDesks, s: DeskSpot) {
  const { thDeg, eastEnd } = spotAngle(s)
  const th = rad(thDeg)
  const up: [number, number] = [Math.sin(th), Math.cos(th)] // away from the hall's centre: up the tiers
  const half = h.desk_depth_m / 2
  let north: [number, number]
  let edge: [number, number]
  let floor_m = s.desk.floor_m
  if (s.gap === 'front') {
    north = up
    edge = polar(h, s.desk.r_m - half, th)
    // The floor in front of a desk is the row below's; in front of the first row, the hall's front floor.
    floor_m = deskIn(h, s.desk.row - 1, thDeg)?.floor_m ?? 0
  } else if (s.gap === 'end') {
    // Along the row (the way th grows is east in the 'behind' picture): our desk lies back along it from its end.
    const along: [number, number] = [Math.cos(th), -Math.sin(th)]
    north = eastEnd ? [-along[0], -along[1]] : along
    edge = polar(h, s.desk.r_m, th)
  } else {
    north = [-up[0], -up[1]]
    edge = polar(h, s.desk.r_m + half, th)
  }
  const east: [number, number] = [-north[1], north[0]]
  return { north, east, edge, floor_m }
}

/**
 * The alignment (room.json) that stands the layout at `spot`: the strip's north edge on our desk's edge on the
 * gap's side, its middle at `along` (or at the desk's end), on the floor of the gap. `box` is the model's own
 * bounding box (x and z), as placeScan centres it.
 */
export function deskFit(h: HallDesks, spot: DeskSpot, box: { min: number[]; max: number[] }, cut_m: number): Required<ScanFit> {
  const [sw] = STRIP_M ?? SIZE_M
  const sh = deskEdge() ?? SIZE_M[1] // the layout's y at our desk's edge: the strip's north edge, or past it
  const [fw, fh] = SIZE_M
  const { north, east, edge, floor_m } = frameAt(h, spot)
  // The layout's origin (the strip's aisle-side west corner) in the model.
  const ox = edge[0] - sh * north[0] - (sw / 2) * east[0]
  const oz = edge[1] - sh * north[1] - (sw / 2) * east[1]
  // Turn so the desk's east lies along the scene's +x (yaw kept to 0.1 degree, as align mode saves it).
  const yaw = Math.round((Math.atan2(east[1], east[0]) * 1800) / Math.PI) / 10
  const p = (yaw * Math.PI) / 180
  const gx = ox - (box.min[0] + box.max[0]) / 2
  const gz = oz - (box.min[2] + box.max[2]) / 2
  const sx = gx * Math.cos(p) + gz * Math.sin(p)
  const sz = -gx * Math.sin(p) + gz * Math.cos(p)
  // The origin must land where the layout puts it in the scene: (-fw / 2, fh / 2).
  const r3 = (v: number) => Math.round(v * 1000) / 1000
  return { offset_m: [r3(-fw / 2 - sx), r3(-(fh / 2 - sz))], yaw_deg: yaw, scale: 1, cut_m, floor_m }
}

/** Where one device should go, in the layout's frame, and how to say it. */
export interface Placement {
  id: string
  xyz: [number, number, number]
  on: 'our desk' | 'facing desk' | 'stand'
  /** One line a tired person can follow. Left and right are as you stand in the spot, facing our desk. */
  words: string
}

/** A device as the guide needs it (frame.ts's NodeInfo fits). */
export interface GuideNode {
  id: string
  name: string
  roles: readonly string[]
  xyz: readonly number[]
}

/** The guide's distances, in metres. One place to change them: a longer cable between the board and the router
 *  may let those two sit 0.3 to 0.6 m apart instead of side by side. */
export interface PlacementPreset {
  /** Between the devices on our desk (the board and the router, tied by a short cable through the hub). */
  nearApartM: number
  /** Between the devices across the gap. */
  farApartM: number
  /** In from the edge of the desk a device sits on. */
  inFromEdgeM: number
  /** A device's radio above the surface it sits on. */
  aboveTopM: number
  /** A facing desk further than this is no use: free-standing instead. */
  facingWithinM: number
  /** Free-standing: this far across the gap from our desk's edge, and this high. */
  standAcrossM: number
  standHighM: number
}
export const PLACEMENT: PlacementPreset = { nearApartM: 0.08, farApartM: 0.7, inFromEdgeM: 0.08, aboveTopM: 0.05, facingWithinM: 1.2, standAcrossM: 1.0, standHighM: 1.0 }

/** A table needs this much of the gap beyond the device on its near edge, or it stands in the next desk. */
const TABLE_ROOM_M = 0.3

/** "70 cm left of the middle", as you stand in the spot facing our desk (the layout's west is your left). */
function sideWords(dx: number): string {
  const cm = Math.round(Math.abs(dx) * 100)
  return cm < 1 ? 'in the middle' : `${cm} cm ${dx < 0 ? 'left' : 'right'} of the middle`
}

/**
 * Where each device should go for a spot, on the furniture the hall has (tonight's hardware result: a body on a
 * Bluetooth line drops it, so the lines must cross the gap). The router and the board (the devices that aren't
 * plain beacons) sit together on our desk, at the edge facing the spot. Every other device goes across the gap,
 * left to right in the order nodes.json has them: on the facing desk's near edge when there is one within
 * FACING_WITHIN_M, else free-standing. Positions are in the layout's frame for a strip `sw` wide and `sh` deep.
 */
export function placementGuide(h: HallDesks, spot: DeskSpot, nodes: readonly GuideNode[], [sw, sh]: readonly number[], preset: PlacementPreset = PLACEMENT): Placement[] {
  const { nearApartM: NEAR_APART_M, farApartM: FAR_APART_M, inFromEdgeM: IN_FROM_EDGE_M, aboveTopM: ABOVE_TOP_M, facingWithinM: FACING_WITHIN_M, standAcrossM: STAND_ACROSS_M, standHighM: STAND_HIGH_M } = preset
  const { floor_m } = frameAt(h, spot)
  const { thDeg, eastEnd } = spotAngle(spot)
  const byX = (a: GuideNode, b: GuideNode) => a.xyz[0] - b.xyz[0] || a.id.localeCompare(b.id)
  const near = nodes.filter((n) => n.roles.includes('router') || !n.roles.includes('beacon')).sort(byX)
  const far = nodes.filter((n) => !near.includes(n)).sort(byX)
  const spread = (i: number, n: number, apart: number) => (i - (n - 1) / 2) * apart
  const cm = (v: number) => Math.round(v * 100) / 100
  const ourTop = spot.desk.floor_m - floor_m + h.desk_height_m

  // The desk across the gap, how far its near edge is from ours, and its floor.
  let facing: { gap: number; floor: number } | null = null
  const half = h.desk_depth_m / 2
  if (spot.gap === 'end') {
    const row = h.desks.filter((d) => d.row === spot.desk.row && d !== spot.desk)
    const next = eastEnd
      ? row.filter((d) => d.th0_deg > spot.desk.th1_deg).sort((a, b) => a.th0_deg - b.th0_deg)[0]
      : row.filter((d) => d.th1_deg < spot.desk.th0_deg).sort((a, b) => b.th1_deg - a.th1_deg)[0]
    if (next) facing = { gap: rad(eastEnd ? next.th0_deg - spot.desk.th1_deg : spot.desk.th0_deg - next.th1_deg) * spot.desk.r_m, floor: next.floor_m }
  } else {
    const d = deskIn(h, spot.desk.row + (spot.gap === 'front' ? -1 : 1), thDeg)
    // Only a desk that reaches this angle is across from us (a row can end before it).
    if (d && rad(outside(d, thDeg)) * d.r_m < 0.3) facing = { gap: Math.abs(d.r_m - spot.desk.r_m) - 2 * half, floor: d.floor_m }
  }
  // A layout that already has a device across the spot (the gate) says itself how deep the gate is and how high
  // each end stands (the two ends are each on the edge of their own table and need not be level). The guide keeps
  // both, so measured numbers in the file drop straight in.
  const acrossNow = nodes.filter((n) => n.xyz[1] < -0.01)
  const gate = acrossNow.length > 0
  const depth = gate ? cm(sh - Math.min(...acrossNow.map((n) => n.xyz[1]))) : STAND_ACROSS_M
  // On the gate the far end stands on its own table in the gap when a table fits there, and on the desk across when
  // it doesn't (between two rows): nothing is ever placed inside the next desk.
  const onDesk = facing !== null && facing.gap > 0 && (gate ? facing.gap < depth + TABLE_ROOM_M : facing.gap <= FACING_WITHIN_M)
  // The desk's edge is read from where the desk's devices stand, so on the gate they are placed on it, not in from it.
  const inFromEdge = gate ? 0 : IN_FROM_EDGE_M

  // One row along our desk's edge and one across the gap. The board's group takes one, the rest the other.
  const ours = (n: GuideNode, dx: number): Placement => ({
    id: n.id, xyz: [cm(sw / 2 + dx), cm(sh + inFromEdge), gate ? n.xyz[2] : cm(ourTop + ABOVE_TOP_M)], on: 'our desk',
    words: `${n.name}: on our desk, at the edge facing the spot, ${sideWords(dx)}`,
  })
  const which = (dx: number, alone: boolean) => (alone ? '' : `, ${sideWords(dx)}`)
  const across = (n: GuideNode, dx: number, alone = false): Placement =>
    onDesk
      ? {
          id: n.id, xyz: [cm(sw / 2 + dx), cm(sh - facing!.gap - inFromEdge), cm(facing!.floor - floor_m + h.desk_height_m + ABOVE_TOP_M)], on: 'facing desk',
          words: gate ? `${n.name}: on the desk across from you, opposite the board${which(dx, alone)}` : `${n.name}: on the desk across the gap, at its near edge, ${sideWords(dx)}`,
        }
      : gate
        ? {
            id: n.id, xyz: [cm(sw / 2 + dx), cm(sh - depth), n.xyz[2]], on: 'stand',
            words: `${n.name}: on its own table, about ${depth} m straight out from the board${which(dx, alone)}`,
          }
        : {
            id: n.id, xyz: [cm(sw / 2 + dx), cm(sh - STAND_ACROSS_M), STAND_HIGH_M], on: 'stand',
            words: `${n.name}: on a stand or chair back, ${STAND_ACROSS_M} m across the gap and ${STAND_HIGH_M} m high, ${sideWords(dx)}`,
          }
  const [boardRow, otherRow] = spot.boardAcross ? [across, ours] : [ours, across]
  return [
    ...near.map((n, i) => boardRow(n, spread(i, near.length, NEAR_APART_M), near.length === 1)),
    ...far.map((n, i) => otherRow(n, spread(i, far.length, FAR_APART_M), far.length === 1)),
  ]
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
    return next ? { desk: next, along: 0.5, gap: from.gap, boardAcross: from.boardAcross } : null
  }
  const sign = dir === 'south' ? 1 : -1
  const row = [...new Set(h.desks.map((d) => d.row))].filter((r) => (r - from.desk.row) * sign > 0).sort((a, b) => (a - b) * sign)[0]
  if (row === undefined) return null
  const gap = (d: HallDesk) => Math.max(d.th0_deg - th, th - d.th1_deg, 0)
  const desk = h.desks.filter((d) => d.row === row).sort((a, b) => gap(a) - gap(b))[0]
  return { desk, along: clampAlong(desk, (th - desk.th0_deg) / (desk.th1_deg - desk.th0_deg)), gap: from.gap, boardAcross: from.boardAcross }
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
  return { desk, along: clampAlong(desk, from.along + metres / length), gap: from.gap, boardAcross: from.boardAcross }
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
  if (hall) {
    const spot = defaultSpot(hall)
    scan.apply(deskFit(hall, spot, scan.box, scan.fit.cut_m ?? HALL_CUT_M))
    scan.defaultDesk = deskName(spot.desk)
  }
  return scan
}
