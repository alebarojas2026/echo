import { BufferAttribute, BufferGeometry, CircleGeometry, DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Vector2, Vector3, type Box3 } from 'three'
import { saveAll, tidyFit } from './align'
import { clampAlong, deskFit, deskName, modelPoint, placementGuide, rowAcross, type DeskSpot, type HallDesk, type HallDesks, type Placement } from './desks'
import type { Fly } from './fly'
import { NODES, SIZE_M, STRIP_M, deskEdge, toScene } from './frame'
import { PlacementGuide } from './guide'
import { BG, TEXT } from './palette'
import type { Scan, ScanFit } from './scan'
import type { RoomView, Shot } from './view'

// Placing the kit by clicking (the front door; align mode's keys stay for fine nudging). The operator opens it
// (the "Place the kit" control, the P key, or ?place=1), the camera goes over the whole hall, and:
//   click a desk   the kit is drawn there as it will stand: the board's end on that desk at the point nearest the
//                  click, the far end on the next row's desk straight across, the spot in the gap between
//   G              the far end on the other side (row behind / row in front)
//   Enter          saves the alignment and every device's place where align mode's S saves them (on the board:
//                  POST /layout), then loads the page again so every part of it stands at the saved place
//   Esc            leaves, with nothing saved and the hall back where it was
// A mouse, a trackpad and a finger all work: a desk is taken on a press that is let go where it began.

/** Which side of the board's desk the far end goes on. */
export type Side = 'behind' | 'front'
export const SIDE_WORDS: Record<Side, string> = { behind: 'the row behind', front: 'the row in front' }

/** What the screen says before a desk is clicked. */
export const PLACE_ASK = 'Click the desk your board is on.'

/** A click this near a desk (metres, on the desk top's level) still takes it: a finger is not a pointer. */
export const PICK_SLACK_M = 0.35

/** How high over the hall the placing view looks down from, and how much of the hall's half-diagonal it shows. */
const PICK_ELEV_DEG = 58
const PICK_FILL = 0.62

/** The mark on each end of the kit, in metres: about a hand's width on the screen from over the hall. */
const DOT_M = 0.32

/** Kept across the page load that follows a save, so the page can say what was saved. */
export const PLACED_KEY = 'room:placed'

type ModelBox = { min: number[]; max: number[] }
const rad = (deg: number) => (deg * Math.PI) / 180

/** A point of the hall's model (x, z) in the scene for an alignment: the way back from desks.ts's modelPoint. */
export function scenePoint([mx, mz]: readonly [number, number], fit: ScanFit, box: ModelBox): [number, number] {
  const [dx, dy] = fit.offset_m ?? [0, 0]
  const p = rad(fit.yaw_deg ?? 0)
  const scale = fit.scale && fit.scale > 0 ? fit.scale : 1
  const wx = mx - (box.min[0] + box.max[0]) / 2
  const wz = mz - (box.min[2] + box.max[2]) / 2
  return [(wx * Math.cos(p) + wz * Math.sin(p)) * scale + dx, (-wx * Math.sin(p) + wz * Math.cos(p)) * scale - dy]
}

/** A desk top's height in the scene for an alignment (the alignment puts the spot's own floor at 0). */
export function deskTopY(h: HallDesks, desk: HallDesk, fit: ScanFit): number {
  return desk.floor_m + h.desk_height_m - (fit.floor_m ?? 0)
}

export interface Ray {
  origin: readonly number[]
  dir: readonly number[]
}

/**
 * The desk a ray from the camera points at, and how far along it (0 its th0 end, 1 its th1 end): the ray is met
 * with each desk top's own level (the rows are tiered), and the desk it lands on wins; nearest the camera when it
 * lands on two. A ray that lands within `slackM` of a desk and on none takes the nearest. Null over open floor.
 */
export function pickDesk(h: HallDesks, ray: Ray, fit: ScanFit, box: ModelBox, slackM = PICK_SLACK_M): { desk: HallDesk; along: number } | null {
  let best: { desk: HallDesk; along: number } | null = null
  let bestMiss = Infinity
  let bestT = Infinity
  if (Math.abs(ray.dir[1]) < 1e-6) return null
  for (const desk of h.desks) {
    const t = (deskTopY(h, desk, fit) - ray.origin[1]) / ray.dir[1]
    if (t <= 0) continue
    const [mx, mz] = modelPoint([ray.origin[0] + t * ray.dir[0], ray.origin[2] + t * ray.dir[2]], fit, box)
    const ex = mx - h.centre_m[0]
    const ez = mz - h.centre_m[1]
    const th = (Math.atan2(ex, ez) * 180) / Math.PI
    const radial = Math.max(0, Math.abs(Math.hypot(ex, ez) - desk.r_m) - h.desk_depth_m / 2)
    const past = rad(Math.max(desk.th0_deg - th, th - desk.th1_deg, 0)) * desk.r_m
    const miss = Math.hypot(radial, past)
    if (miss > slackM) continue
    if (miss < bestMiss - 1e-9 || (miss <= bestMiss + 1e-9 && t < bestT)) {
      best = { desk, along: clampAlong(desk, (th - desk.th0_deg) / (desk.th1_deg - desk.th0_deg)) }
      bestMiss = miss
      bestT = t
    }
  }
  return best
}

/**
 * The side the far end goes on at a desk: the side asked for when a row's desk reaches across from this point,
 * else the other side when that has one. `swapped` says the side asked for had no row. With no row on either
 * side the side asked for stands (the far end then goes on a table of its own).
 */
export function sideAt(h: HallDesks, at: { desk: HallDesk; along: number }, want: Side): { side: Side; swapped: boolean } {
  const other: Side = want === 'behind' ? 'front' : 'behind'
  if (rowAcross(h, { ...at, gap: want })) return { side: want, swapped: false }
  return rowAcross(h, { ...at, gap: other }) ? { side: other, swapped: true } : { side: want, swapped: false }
}

/** "Board and Pi A": names joined as people say them, the board (the device that is no router) first. */
function names(ids: readonly string[]): string {
  const router = (id: string) => (NODES[id]?.roles.includes('router') ? 1 : 0)
  const list = [...ids].sort((a, b) => router(a) - router(b)).map((id) => NODES[id]?.name ?? id)
  return list.length <= 1 ? (list[0] ?? '') : `${list.slice(0, -1).join(', ')} and ${list.at(-1)}`
}

/** Where the kit stands for a set of placements, in one sentence: "Board and Pi A on this desk, Pi B on the row behind." */
export function standWords(places: readonly Placement[], side: Side, desk = 'this desk'): string {
  const near = places.filter((p) => p.on === 'our desk').map((p) => p.id)
  const far = places.filter((p) => p.on !== 'our desk')
  const where = far.some((p) => p.on === 'facing desk') ? `on ${SIDE_WORDS[side]}` : 'on a table of its own across the gap'
  return `${names(near)} on ${desk}${far.length ? `, ${names(far.map((p) => p.id))} ${where}` : ''}.`
}

/** What the screen says with a desk clicked. */
export function chosenWords(places: readonly Placement[], side: Side, swapped: boolean): string {
  const other: Side = side === 'behind' ? 'front' : 'behind'
  const none = swapped ? `No row ${other === 'behind' ? 'behind' : 'in front of'} this desk. ` : ''
  return `${none}${standWords(places, side)} Press Enter to save, or click another desk.`
}

/** What the page says after the save: the place in words a person can check against the hall. */
export function savedWords(desk: HallDesk, places: readonly Placement[], side: Side): string {
  return `Saved: ${deskName(desk)}. ${standWords(places, side, 'that desk')}`
}

/**
 * The whole hall from above at a slight angle, the same way up whichever desk the layout stands at: the camera
 * goes round with the hall's model (`yawDeg`, the alignment's turn), so clicking a desk in another block does not
 * swing the picture. `halfDiagM` is the model's own half-diagonal on the floor, which no turn changes.
 */
export function pickShot(bounds: Box3, yawDeg: number, halfDiagM: number): Shot {
  const target = new Vector3((bounds.min.x + bounds.max.x) / 2, bounds.min.y, (bounds.min.z + bounds.max.z) / 2)
  return { elevDeg: PICK_ELEV_DEG, azimDeg: yawDeg, target, radiusM: Math.max(2, halfDiagM * PICK_FILL) }
}

/**
 * Where the two ends of the kit are marked in the whole hall, in the scene: the middle of the devices on the
 * board's desk and the middle of those across the gap, and for each a point for its name, pushed away from the
 * other end so the two names never sit on each other (the ends are a metre apart, a few pixels from up here).
 * `far` is null for a layout with nothing across the gap.
 */
export function kitEnds(places: readonly Placement[], pushM = 1.6): { near: Ends; far: Ends | null } | null {
  const middle = (list: readonly Placement[]): [number, number, number] | null => {
    if (!list.length) return null
    const sum = list.map((p) => toScene(p.xyz)).reduce((a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], [0, 0, 0])
    return [sum[0] / list.length, sum[1] / list.length, sum[2] / list.length]
  }
  const near = middle(places.filter((p) => p.on === 'our desk'))
  const far = middle(places.filter((p) => p.on !== 'our desk'))
  if (!near) return null
  if (!far) return { near: { at: near, word: [near[0], near[1], near[2] - pushM] }, far: null }
  const len = Math.hypot(near[0] - far[0], near[2] - far[2]) || 1
  const [ux, uz] = [(near[0] - far[0]) / len, (near[2] - far[2]) / len]
  return {
    near: { at: near, word: [near[0] + ux * pushM, near[1], near[2] + uz * pushM] },
    far: { at: far, word: [far[0] - ux * pushM, far[1], far[2] - uz * pushM] },
  }
}
export interface Ends {
  at: [number, number, number]
  word: [number, number, number]
}

/** A desk top as a flat strip of triangles in the scene (x, y, z triples), a little above the top itself. */
export function deskStrip(h: HallDesks, desk: HallDesk, fit: ScanFit, box: ModelBox, liftM = 0.04): Float32Array {
  const steps = Math.max(2, Math.ceil((desk.th1_deg - desk.th0_deg) / 2))
  const y = deskTopY(h, desk, fit) + liftM
  const at = (r: number, thDeg: number): [number, number] =>
    scenePoint([h.centre_m[0] + r * Math.sin(rad(thDeg)), h.centre_m[1] + r * Math.cos(rad(thDeg))], fit, box)
  const out: number[] = []
  const [r0, r1] = [desk.r_m - h.desk_depth_m / 2, desk.r_m + h.desk_depth_m / 2]
  for (let i = 0; i < steps; i++) {
    const a = desk.th0_deg + ((desk.th1_deg - desk.th0_deg) * i) / steps
    const b = desk.th0_deg + ((desk.th1_deg - desk.th0_deg) * (i + 1)) / steps
    const [p, q, r, s] = [at(r0, a), at(r1, a), at(r1, b), at(r0, b)]
    out.push(p[0], y, p[1], q[0], y, q[1], r[0], y, r[1], p[0], y, p[1], r[0], y, r[1], s[0], y, s[1])
  }
  return new Float32Array(out)
}

export interface PlaceDeps {
  view: RoomView
  scan: Scan
  fly: Fly
  hall: HallDesks
  /** Sits every device on what the hall has under it where the hall stands now. */
  reseat: () => void
  /** The hall shot for the hall as it stands now, for handing the camera back. */
  hallShotNow: () => Shot
}

/** The words saved by the last placing, once (then forgotten), or null. */
export function takePlacedWords(store: Pick<Storage, 'getItem' | 'removeItem'> | null = typeof sessionStorage === 'undefined' ? null : sessionStorage): string | null {
  try {
    const said = store?.getItem(PLACED_KEY) ?? null
    if (said) store!.removeItem(PLACED_KEY)
    return said
  } catch {
    return null // storage is off in this browser: the page still works, it just does not say what was saved
  }
}

/**
 * Offers the placing to the operator: the control (shown with the operator's view, room.css), the P key, and
 * ?place=1. Also says what the last placing saved, when this page load follows one. Returns the opener.
 */
export function offerPlacing(deps: PlaceDeps, openNow = false): () => void {
  const { view, fly } = deps
  let leave: (() => void) | null = null
  const open = () => {
    if (leave || view.host.dataset.replay === 'on') return
    leave = startPlacing(deps, () => (leave = null))
  }
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'room-place-open'
  button.dataset.testid = 'place-open'
  button.textContent = 'Place the kit'
  button.addEventListener('click', open)
  if (view.host.dataset.op === '1') button.dataset.op = '1'
  // On the page, not in the room: the panels' operator drawer lies over the whole screen while it is open, and
  // this control sits in its top right corner, above it.
  document.body.append(button)
  document.addEventListener('keydown', (event) => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return
    if ((event.target as HTMLElement | null)?.closest?.('input,select,textarea,[contenteditable]')) return
    if ((event.key === 'p' || event.key === 'P') && !leave) open()
  })
  const said = takePlacedWords()
  if (said) {
    // The page load after a save: the place in words, and the camera comes down to it so it is seen.
    const note = document.createElement('p')
    note.className = 'room-placed'
    note.dataset.testid = 'place-saved'
    note.setAttribute('role', 'status')
    note.textContent = said
    document.body.append(note)
    view.host.classList.add('room--placed')
    // While the place is shown the operator drawer steps aside (room.css): it lies over the whole screen.
    document.documentElement.dataset.roomPlaced = '1'
    fly.showPlace(PLACED_SHOW_MS)
    setTimeout(() => {
      note.remove()
      view.host.classList.remove('room--placed')
      delete document.documentElement.dataset.roomPlaced
    }, PLACED_SHOW_MS + 4000)
  }
  if (openNow) open()
  return open
}

/** How long the camera stays down at the saved place before it goes back to the hall (when the card is waiting). */
const PLACED_SHOW_MS = 6000

/** Turns the placing on. Returns the way out (nothing saved). */
export function startPlacing({ view, scan, fly, hall, reseat, hallShotNow }: PlaceDeps, onLeave: () => void): () => void {
  const before = tidyFit(scan.fit)
  const strip = STRIP_M ?? SIZE_M
  const halfDiag = Math.hypot(scan.box.max[0] - scan.box.min[0], scan.box.max[2] - scan.box.min[2]) / 2
  let want: Side = 'behind'
  let chosen: { desk: HallDesk; along: number } | null = null
  let side: Side = 'behind'
  let places: Placement[] = []
  let saving = false

  const root = document.documentElement
  root.dataset.roomPlacing = '1'
  // The operator drawer closes, as Esc closes it: its own keys (R reset, M and H router, T lesson, B baseline) act
  // only while it is open, and none of them may fire while a desk is being chosen. Nothing keeps the focus either:
  // Enter on a control that had it would press that control.
  const drawer = document.querySelector<HTMLElement>('.hud-operator')
  if (drawer) drawer.hidden = true
  ;(document.activeElement as HTMLElement | null)?.blur?.()
  const panel = document.createElement('div')
  panel.className = 'room-place'
  panel.dataset.testid = 'place'
  panel.innerHTML =
    '<p class="room-place-say" role="status"></p><div class="room-place-keys">' +
    '<button type="button" data-do="flip" disabled>Other side of the desk (G)</button>' +
    '<button type="button" data-do="save" disabled>Save (Enter)</button>' +
    '<button type="button" data-do="leave">Leave (Esc)</button></div>'
  document.body.append(panel)
  const say = panel.querySelector<HTMLElement>('.room-place-say')!
  const [flipButton, saveButton] = ['flip', 'save'].map((d) => panel.querySelector<HTMLButtonElement>(`[data-do="${d}"]`)!)
  say.textContent = PLACE_ASK

  // The desk under the pointer and the desk taken, drawn on the desk tops over everything.
  const paint = (color: number, opacity: number) => {
    const mesh = new Mesh(new BufferGeometry(), new MeshBasicMaterial({ color, transparent: true, opacity, depthTest: false, depthWrite: false, side: DoubleSide }))
    mesh.renderOrder = 25
    mesh.visible = false
    view.scene.add(mesh)
    return mesh
  }
  const hoverMesh = paint(TEXT, 0.35)
  const chosenMesh = paint(TEXT, 0.8)
  // The two ends of the kit, as they will stand: a mark on each desk and its devices' names beside it. The board's
  // end is on the lit desk, so its mark is dark; the far end's is light on the desk across.
  const dot = (color: number) => {
    const mesh = new Mesh(new CircleGeometry(DOT_M, 24).rotateX(-Math.PI / 2), new MeshBasicMaterial({ color, depthTest: false, depthWrite: false }))
    mesh.renderOrder = 26
    mesh.visible = false
    view.scene.add(mesh)
    return mesh
  }
  const dots = [dot(BG), dot(TEXT)]
  // The names are this mode's own (not the view's labels, which give way to the figure and to each other: here
  // both names must always show).
  const tagLayer = document.createElement('div')
  tagLayer.className = 'room-place-tags'
  const tags = [0, 1].map(() => {
    const tag = document.createElement('span')
    tag.className = 'room-place-tag'
    tag.hidden = true
    tagLayer.append(tag)
    return tag
  })
  view.host.append(tagLayer)
  let ends: ReturnType<typeof kitEnds> = null
  const placeTags = () => {
    const [w, h] = view.size
    const list = ends ? [ends.near, ends.far] : [null, null]
    list.forEach((end, i) => {
      tags[i].hidden = !end
      if (!end) return
      const p = new Vector3(...end.word).project(view.camera)
      tags[i].style.transform = `translate(${(((p.x + 1) / 2) * w).toFixed(1)}px, ${(((1 - p.y) / 2) * h).toFixed(1)}px)`
    })
  }
  const showEnds = () => {
    ends = kitEnds(places)
    const list = ends ? [ends.near, ends.far] : [null, null]
    const words = [names(places.filter((p) => p.on === 'our desk').map((p) => p.id)), names(places.filter((p) => p.on !== 'our desk').map((p) => p.id))]
    list.forEach((end, i) => {
      dots[i].visible = !!end
      tags[i].textContent = words[i]
      if (end) dots[i].position.set(end.at[0], end.at[1] + 0.06, end.at[2])
    })
  }
  view.onResize(() => {
    if (root.dataset.roomPlacing) requestAnimationFrame(placeTags) // after the camera has been fitted to the new size
  })
  let hovered: HallDesk | null = null
  const draw = (mesh: Mesh<BufferGeometry>, desk: HallDesk | null) => {
    mesh.visible = !!desk
    if (desk) {
      mesh.geometry.dispose()
      mesh.geometry = new BufferGeometry()
      mesh.geometry.setAttribute('position', new BufferAttribute(deskStrip(hall, desk, scan.fit, scan.box), 3))
    }
    view.requestRender()
  }
  const marks = new PlacementGuide(view)

  const frame = () => fly.take(pickShot(scan.bounds(), scan.fit.yaw_deg ?? 0, halfDiag))
  frame()

  const stand = () => {
    if (!chosen) return
    const at = sideAt(hall, chosen, want)
    side = at.side
    const spot: DeskSpot = { ...chosen, gap: side }
    scan.apply(deskFit(hall, spot, scan.box, before.cut_m))
    reseat()
    places = placementGuide(hall, spot, Object.values(NODES), [strip[0], deskEdge() ?? strip[1]])
    marks.show(places)
    showEnds()
    frame()
    placeTags()
    draw(chosenMesh, chosen.desk)
    draw(hoverMesh, (hovered = null))
    say.textContent = chosenWords(places, side, at.swapped)
    flipButton.disabled = saveButton.disabled = false
    view.host.dataset.placing = JSON.stringify({ row: chosen.desk.row + 1, block: chosen.desk.wedge + 1, along: Math.round(chosen.along * 100) / 100, side })
  }

  const ray = new Raycaster()
  const deskAt = (event: PointerEvent) => {
    const rect = view.renderer.domElement.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    ray.setFromCamera(new Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, 1 - ((event.clientY - rect.top) / rect.height) * 2), view.camera)
    return pickDesk(hall, { origin: ray.ray.origin.toArray(), dir: ray.ray.direction.toArray() }, scan.fit, scan.box)
  }
  let down: { x: number; y: number } | null = null
  const onDown = (event: PointerEvent) => (down = { x: event.clientX, y: event.clientY })
  const onMove = (event: PointerEvent) => {
    if (event.pointerType !== 'mouse') return
    const desk = deskAt(event)?.desk ?? null
    if (desk !== hovered) draw(hoverMesh, (hovered = desk === chosen?.desk ? null : desk))
    view.host.style.cursor = desk ? 'pointer' : ''
  }
  const onUp = (event: PointerEvent) => {
    const began = down
    down = null
    // A press let go where it began: a drag or a pinch is not a choice.
    if (!began || Math.hypot(event.clientX - began.x, event.clientY - began.y) > 10 || saving) return
    const hit = deskAt(event)
    if (!hit) return
    chosen = hit
    stand()
  }
  const canvas = view.renderer.domElement
  canvas.addEventListener('pointerdown', onDown)
  canvas.addEventListener('pointermove', onMove)
  canvas.addEventListener('pointerup', onUp)

  const flip = () => {
    if (!chosen || saving) return
    want = side === 'behind' ? 'front' : 'behind'
    stand()
  }
  const save = () => {
    if (!chosen || saving) return
    saving = true
    saveButton.disabled = flipButton.disabled = true
    say.textContent = 'Saving…'
    marks.take()
    const said = savedWords(chosen.desk, places, side)
    void saveAll(scan.fit, undefined, marks.moved()).then((result) => {
      if (!result.startsWith('Saved')) {
        // Nowhere to save it from this page (no board behind it): say so, and stay so nothing is lost.
        saving = false
        saveButton.disabled = flipButton.disabled = false
        say.textContent = `Not saved on the board. ${result}`
        return
      }
      const kept = result.includes('NOT kept') ? ' The devices’ places were not kept: this board does not take them yet.' : ''
      try {
        sessionStorage.setItem(PLACED_KEY, said + kept)
      } catch {
        // storage is off: the page still loads at the saved place
      }
      say.textContent = said + kept
      view.host.dataset.placed = '1'
      // Every part of the page reads the layout when it loads: loading it again is what makes each of them stand
      // at the saved place, and it is the same thing a second laptop or a later visit will see.
      const url = new URL(location.href)
      url.searchParams.delete('place')
      setTimeout(() => location.replace(url), 600)
    })
  }
  const out = () => {
    if (saving) return
    canvas.removeEventListener('pointerdown', onDown)
    canvas.removeEventListener('pointermove', onMove)
    canvas.removeEventListener('pointerup', onUp)
    document.removeEventListener('keydown', onKey, true)
    marks.hide()
    for (const mesh of [hoverMesh, chosenMesh, ...dots]) {
      view.scene.remove(mesh)
      mesh.geometry.dispose()
      mesh.material.dispose()
    }
    tagLayer.remove()
    panel.remove()
    delete root.dataset.roomPlacing
    delete view.host.dataset.placing
    view.host.style.cursor = ''
    scan.apply(before)
    reseat()
    fly.give(hallShotNow())
    onLeave()
  }
  const onKey = (event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return
    if ((event.target as HTMLElement | null)?.closest?.('input,select,textarea,[contenteditable]')) return
    const key = event.key
    // No key reaches the rest of the page while a desk is being chosen: not the panels' (O, /, the arrows), not
    // the room's own (H). Only this mode's keys do anything.
    event.stopPropagation()
    if (key === 'Enter') save()
    else if (key === 'Escape') out()
    else if (key === 'g' || key === 'G') flip()
    else return
    event.preventDefault()
  }
  document.addEventListener('keydown', onKey, true)
  panel.addEventListener('click', (event) => {
    const todo = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-do]')?.dataset.do
    if (todo === 'flip') flip()
    else if (todo === 'save') save()
    else if (todo === 'leave') out()
  })
  return out
}
