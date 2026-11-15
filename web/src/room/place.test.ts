import { Box3, Vector3 } from 'three'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { deskFit, modelPoint, parseDesks, placementGuide, rowAcross, type HallDesks } from './desks'
import { NODES, STRIP_M, applyLayout, deskEdge } from './frame'
import { DESK_LAYOUT, GATE_LAYOUT } from './layouts.fixture'
import { PICK_SLACK_M, PLACED_KEY, askWords, chosenWords, deskStrip, deskTopY, flipWords, kitEnds, pickDesk, pickShot, savedWords, scenePoint, sideAt, standWords, takePlacedWords } from './place'

// A small hall in the file's own form: three rows of two blocks around one centre, rising a step every row, and
// the middle row's east block missing so one desk has no row behind it there. Not a real room's numbers.
const HALL: HallDesks = parseDesks({
  centre_m: [0, -10],
  desk_depth_m: 0.6,
  desk_height_m: 0.74,
  desks: [0, 1, 2].flatMap((row) => [
    { row, wedge: 0, r_m: 20 + 1.5 * row, th0_deg: -14, th1_deg: -1, floor_m: 0.15 * (row + 1) },
    { row, wedge: 1, r_m: 20 + 1.5 * row, th0_deg: 1, th1_deg: 14, floor_m: 0.15 * (row + 1) },
  ]),
})!
const BOX = { min: [-15, 0, -1], max: [17, 6, 22] }
const desk = (row: number, wedge: number) => HALL.desks.find((d) => d.row === row && d.wedge === wedge)!
const FIT = { offset_m: [3.2, -1.4] as [number, number], yaw_deg: 37.5, scale: 1, cut_m: 12, floor_m: 0.3 }

/** A point of a desk's middle line in the scene, at its top. */
function onDesk(row: number, wedge: number, along: number, fit = FIT, dr = 0): [number, number, number] {
  const d = desk(row, wedge)
  const th = ((d.th0_deg + (d.th1_deg - d.th0_deg) * along) * Math.PI) / 180
  const [x, z] = scenePoint([HALL.centre_m[0] + (d.r_m + dr) * Math.sin(th), HALL.centre_m[1] + (d.r_m + dr) * Math.cos(th)], fit, BOX)
  return [x, deskTopY(HALL, d, fit), z]
}
/** A ray from a camera high to the south-west of a scene point, through it. */
function rayThrough([x, y, z]: [number, number, number]) {
  const origin = [x - 12, y + 30, z + 18]
  const len = Math.hypot(12, 30, 18)
  return { origin, dir: [12 / len, -30 / len, -18 / len] }
}

describe('placing the kit by clicking a desk', () => {
  beforeAll(() => expect(applyLayout(GATE_LAYOUT)).toBe(true))
  afterAll(() => expect(applyLayout(DESK_LAYOUT)).toBe(true))

  it('finds the way from the model to the scene and back, for any alignment', () => {
    for (const fit of [FIT, { offset_m: [0, 0] as [number, number], yaw_deg: 0, scale: 1 }, { offset_m: [-8, 5] as [number, number], yaw_deg: -171.2, scale: 1.25 }]) {
      const [mx, mz] = modelPoint(scenePoint([4.2, 11.7], fit, BOX), fit, BOX)
      expect(mx).toBeCloseTo(4.2)
      expect(mz).toBeCloseTo(11.7)
    }
  })

  it('takes the desk the pointer is over, at the point along it nearest the click', () => {
    const hit = pickDesk(HALL, rayThrough(onDesk(2, 0, 0.3)), FIT, BOX)!
    expect(hit.desk).toBe(desk(2, 0))
    expect(hit.along).toBeCloseTo(0.3)
    expect(pickDesk(HALL, rayThrough(onDesk(0, 1, 0.75)), FIT, BOX)).toMatchObject({ desk: desk(0, 1) })
    // The same click under another alignment (the hall turned and moved under the layout) is the same desk.
    const turned = deskFit(HALL, { desk: desk(1, 1), along: 0.5, gap: 'front' }, BOX, 12)
    expect(pickDesk(HALL, rayThrough(onDesk(2, 0, 0.3, turned)), turned, BOX)).toMatchObject({ desk: desk(2, 0) })
    // Near a desk's end the strip still fits on the desk: the kit is kept half a strip in from the end.
    const end = pickDesk(HALL, rayThrough(onDesk(1, 0, 0.999)), FIT, BOX)!
    expect(end.desk).toBe(desk(1, 0))
    expect(end.along).toBeLessThan(0.999)
    expect(end.along).toBeGreaterThan(0.8)
  })

  it('takes the nearest desk for a finger that lands just off one, and nothing over open floor', () => {
    const d = desk(1, 0)
    const off = HALL.desk_depth_m / 2 + PICK_SLACK_M - 0.05 // just outside the desk top, inside the slack
    expect(pickDesk(HALL, rayThrough(onDesk(1, 0, 0.5, FIT, off)), FIT, BOX)).toMatchObject({ desk: d })
    // The middle of the gap between two rows (0.9 m of floor): neither desk.
    expect(pickDesk(HALL, rayThrough(onDesk(1, 0, 0.5, FIT, 0.75)), FIT, BOX)).toBeNull()
    // The front of the hall, far from any desk; and a ray that never comes down.
    expect(pickDesk(HALL, rayThrough([...scenePoint([0, 0], FIT, BOX), 0].map((v, i) => (i === 1 ? 0 : v)) as [number, number, number]), FIT, BOX)).toBeNull()
    expect(pickDesk(HALL, { origin: [0, 5, 0], dir: [1, 0, 0] }, FIT, BOX)).toBeNull()
  })

  it('puts the far end on the row behind, on the row in front when asked, and on the other side when there is no row', () => {
    const middle = { desk: desk(1, 0), along: 0.5 }
    expect(sideAt(HALL, middle, 'behind')).toEqual({ side: 'behind', swapped: false })
    expect(sideAt(HALL, middle, 'front')).toEqual({ side: 'front', swapped: false })
    // The back row has nothing behind it, the front row nothing in front.
    expect(sideAt(HALL, { desk: desk(2, 1), along: 0.5 }, 'behind')).toEqual({ side: 'front', swapped: true })
    expect(sideAt(HALL, { desk: desk(0, 1), along: 0.5 }, 'front')).toEqual({ side: 'behind', swapped: true })
    expect(rowAcross(HALL, { desk: desk(2, 1), along: 0.5, gap: 'behind' })).toBeNull()
    expect(rowAcross(HALL, { desk: desk(1, 0), along: 0.5, gap: 'behind' })).toBe(desk(2, 0))
    expect(rowAcross(HALL, { desk: desk(1, 0), along: 0.5, gap: 'front' })).toBe(desk(0, 0))
    // A hall of one row: no row either way, so the side asked for stands (the far end goes on its own table).
    const one = parseDesks({ centre_m: [0, 0], desk_depth_m: 0.6, desks: [{ row: 0, wedge: 0, r_m: 10, th0_deg: -10, th1_deg: 10, floor_m: 0 }] })!
    expect(sideAt(one, { desk: one.desks[0], along: 0.5 }, 'front')).toEqual({ side: 'front', swapped: false })
  })

  it('says where the kit stands in one sentence, from the layout’s own names', () => {
    const spot = { desk: desk(1, 0), along: 0.5, gap: 'behind' as const }
    const places = placementGuide(HALL, spot, Object.values(NODES), [STRIP_M![0], deskEdge() ?? STRIP_M![1]])
    // Before a click the desk is named by the devices on it (the kit spans two rows), and the far end by its row.
    expect(askWords()).toEqual({
      ask: 'Click the desk the board and Pi A are on.',
      help: 'Pi B is on the row behind it. Press G if Pi B is on the row in front.',
    })
    // The devices the question names are the ones the guide then puts on the clicked desk.
    const onDesk = places.filter((p) => p.on === 'our desk').map((p) => NODES[p.id].name)
    for (const name of onDesk) expect(askWords().ask.toLowerCase()).toContain(name.toLowerCase())
    for (const p of places.filter((q) => q.on !== 'our desk')) expect(askWords().ask).not.toContain(NODES[p.id].name)
    expect(askWords([{ id: 'unoq', name: 'Board', roles: [], xyz: [0, 0, 0] }])).toEqual({ ask: 'Click the desk the board is on.', help: '' })
    // With a desk clicked the line names the key for the other side, and says nothing when that side has no row.
    expect(flipWords(places, 'behind', true)).toBe('Press G if Pi B is on the row in front.')
    expect(flipWords(places, 'front', true)).toBe('Press G if Pi B is on the row behind.')
    expect(flipWords(places, 'front', false)).toBe('')
    expect(standWords(places, 'behind')).toBe('Board and Pi A on this desk, Pi B on the row behind.')
    expect(chosenWords(places, 'behind', false)).toBe('Board and Pi A on this desk, Pi B on the row behind. Press Enter to save, or click another desk.')
    expect(chosenWords(places, 'front', true)).toBe('No row behind this desk. Board and Pi A on this desk, Pi B on the row in front. Press Enter to save, or click another desk.')
    expect(chosenWords(places, 'behind', true)).toMatch(/^No row in front of this desk\. /)
    expect(savedWords(desk(1, 0), places, 'behind')).toBe('Saved: Row 2, block 1. Board and Pi A on that desk, Pi B on the row behind.')
    // With no desk across, the far end is on a table of its own and the words say that, not a row.
    const alone = places.map((p) => (p.on === 'our desk' ? p : { ...p, on: 'stand' as const }))
    expect(standWords(alone, 'behind')).toBe('Board and Pi A on this desk, Pi B on a table of its own across the gap.')
  })

  it('names the two ends of the kit apart from each other, each beside its own end', () => {
    const spot = { desk: desk(1, 0), along: 0.5, gap: 'behind' as const }
    const places = placementGuide(HALL, spot, Object.values(NODES), [STRIP_M![0], deskEdge() ?? STRIP_M![1]])
    const ends = kitEnds(places)!
    const gap = Math.hypot(ends.near.at[0] - ends.far!.at[0], ends.near.at[2] - ends.far!.at[2])
    expect(gap).toBeGreaterThan(0.7) // the ends are about a metre apart
    expect(gap).toBeLessThan(1.3)
    const words = Math.hypot(ends.near.word[0] - ends.far!.word[0], ends.near.word[2] - ends.far!.word[2])
    expect(words).toBeCloseTo(gap + 3.2) // each name pushed 1.6 m away from the other end
    expect(kitEnds([])).toBeNull()
    expect(kitEnds(places.filter((p) => p.on === 'our desk'))!.far).toBeNull()
  })

  it('looks at the hall the same way up whichever desk the layout stands at', () => {
    const a = pickShot(new Box3(new Vector3(-10, -0.3, -20), new Vector3(20, 6, 12)), 0, 20)
    const b = pickShot(new Box3(new Vector3(-30, -0.9, -5), new Vector3(8, 5.4, 25)), 153.6, 20)
    expect(a.radiusM).toBe(b.radiusM) // the hall is the same size on screen
    expect(a.elevDeg).toBe(b.elevDeg)
    expect(a.azimDeg).toBe(0)
    expect(b.azimDeg).toBe(153.6) // the camera goes round with the hall
    expect(b.target.toArray()).toEqual([-11, -0.9, 10]) // and looks at its middle, on its own lowest floor
    expect(a.elevDeg).toBeGreaterThan(45) // from above, so the rows do not hide each other
  })

  it('draws a desk top where the hall’s model has it', () => {
    const d = desk(1, 1)
    const strip = deskStrip(HALL, d, FIT, BOX, 0)
    expect(strip.length % 18).toBe(0) // two triangles a step
    for (let i = 0; i < strip.length; i += 3) {
      expect(strip[i + 1]).toBeCloseTo(deskTopY(HALL, d, FIT))
      const [mx, mz] = modelPoint([strip[i], strip[i + 2]], FIT, BOX)
      const r = Math.hypot(mx - HALL.centre_m[0], mz - HALL.centre_m[1])
      expect(Math.abs(r - d.r_m)).toBeCloseTo(HALL.desk_depth_m / 2)
    }
  })

  it('says once, after the page loads again, what was saved', () => {
    const kept = new Map([[PLACED_KEY, 'Saved: Row 7, block 1.']])
    const store = { getItem: (k: string) => kept.get(k) ?? null, removeItem: (k: string) => void kept.delete(k) }
    expect(takePlacedWords(store)).toBe('Saved: Row 7, block 1.')
    expect(takePlacedWords(store)).toBeNull()
    expect(takePlacedWords(null)).toBeNull()
    expect(takePlacedWords({ getItem: () => { throw new Error('storage is off') }, removeItem: () => {} })).toBeNull()
  })
})
