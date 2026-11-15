import type { Material, Object3D } from 'three'
import { deskFit, deskName, loadDesks, modelPoint, nearestSpot, slideDesk, stepDesk, type DeskSpot, type DeskStep, type HallDesks } from './desks'
import type { HallBeacons } from './devices'
import { SIZE_M, STRIP_M, toScene } from './frame'
import { DEFAULT_CUT_M, type Scan, type ScanFit } from './scan'
import type { Stage } from './stage'
import { roomShot, topShot, type RoomView } from './view'

// Align mode (?align=1): line an on-site scan up with the square by eye, then save room.json. No numbers
// are typed. The square, its zone lines and the nodes draw over the scan, so the scanned stands and floor
// markers can be put right under them.
//   arrows  move the scan east / north: 2 cm (Shift: 10 cm)
//   Q / E   turn it left / right: 1 degree (Shift: 15)
//   + / -   scale it by 1%
//   [ / ]   lower / raise the cut height by 5 cm
//   PgUp / PgDn  raise / lower the model: 2 cm (Shift: one 0.156 m riser), for a square on a tier
//   V       straight-down view, or back to the normal one
//   S       save room.json
// On the desk layout, when the build has the hall's desks (desks.ts), the strip snaps to a real desk, on that
// desk's tier, so nothing is lined up by eye:
//   D       stand at the nearest desk
//   I / K   the next row toward the front / up the tiers
//   J / L   the next block west / east
//   U / O   along the desk, west / east: 10 cm (Shift: 50 cm)
// Hall beacons (devices.ts): Tab picks the next heard one (or a click on it); while one is picked the arrows move
// it on the floor (10 cm, Shift 1 m) and it can be dragged, from the "new beacon" tray too; Esc lets go. S saves
// their positions into radio/nodes.json as well.

const STEP_M = 0.02
const BIG_STEP_M = 0.1
const TURN_DEG = 1
const BIG_TURN_DEG = 15
const SCALE_STEP = 1.01
const CUT_STEP_M = 0.05
const MIN_CUT_M = 0.2
const FLOOR_STEP_M = 0.02
const RISER_M = 0.156 // one step of the judging hall's tiers (HALL.md)

const round = (v: number, places: number) => Number(v.toFixed(places))

/** Every field filled in and rounded, so the saved file is complete and readable. Yaw stays in -180..180. */
export function tidyFit(fit: ScanFit): Required<ScanFit> {
  const [east, north] = fit.offset_m ?? [0, 0]
  const yaw = ((((fit.yaw_deg ?? 0) % 360) + 540) % 360) - 180
  return {
    offset_m: [round(east, 3), round(north, 3)],
    yaw_deg: round(yaw === -180 ? 180 : yaw, 1),
    scale: round(fit.scale && fit.scale > 0 ? fit.scale : 1, 3),
    cut_m: round(fit.cut_m ?? DEFAULT_CUT_M, 2),
    floor_m: round(fit.floor_m ?? 0, 3),
  }
}

/** The alignment after one key press, or null when the key isn't one of align mode's. */
export function nudge(fit: ScanFit, key: string, shift: boolean): Required<ScanFit> | null {
  const f = tidyFit(fit)
  const [east, north] = f.offset_m
  const step = shift ? BIG_STEP_M : STEP_M
  const turn = shift ? BIG_TURN_DEG : TURN_DEG
  switch (key) {
    case 'ArrowRight': return tidyFit({ ...f, offset_m: [east + step, north] })
    case 'ArrowLeft': return tidyFit({ ...f, offset_m: [east - step, north] })
    case 'ArrowUp': return tidyFit({ ...f, offset_m: [east, north + step] })
    case 'ArrowDown': return tidyFit({ ...f, offset_m: [east, north - step] })
    // Q turns left (counter-clockwise seen from above, like yaw_deg), E turns right.
    case 'q': case 'Q': return tidyFit({ ...f, yaw_deg: f.yaw_deg + turn })
    case 'e': case 'E': return tidyFit({ ...f, yaw_deg: f.yaw_deg - turn })
    case '+': case '=': return tidyFit({ ...f, scale: f.scale * SCALE_STEP })
    case '-': case '_': return tidyFit({ ...f, scale: f.scale / SCALE_STEP })
    case ']': case '}': return tidyFit({ ...f, cut_m: f.cut_m + CUT_STEP_M })
    case '[': case '{': return tidyFit({ ...f, cut_m: Math.max(MIN_CUT_M, f.cut_m - CUT_STEP_M) })
    // floor_m is how far the model sits below our floor: PageDown lowers the model, PageUp raises it.
    case 'PageDown': return tidyFit({ ...f, floor_m: f.floor_m + (shift ? RISER_M : FLOOR_STEP_M) })
    case 'PageUp': return tidyFit({ ...f, floor_m: f.floor_m - (shift ? RISER_M : FLOOR_STEP_M) })
  }
  return null
}

/** Two lines a person can read off the screen: where, then how. */
export function describeFit(fit: ScanFit): string {
  const f = tidyFit(fit)
  const signed = (v: number, places: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(places)}`
  const where = `East ${signed(f.offset_m[0], 2)} m · North ${signed(f.offset_m[1], 2)} m`
  return `${where}\nTurn ${signed(f.yaw_deg, 1)}° · Scale ${f.scale.toFixed(3)} · Cut ${f.cut_m.toFixed(2)} m · Floor ${signed(-f.floor_m, 2)} m`
}

/** Draws everything under `root` except `skip` over whatever is in front of it (the scan). */
function drawOnTop(root: Object3D, skip: Object3D) {
  if (root === skip) return
  const material = (root as Object3D & { material?: Material | Material[] }).material
  for (const m of material ? [material].flat() : []) m.depthTest = false
  if (material) root.renderOrder = 10
  for (const child of root.children) drawOnTop(child, skip)
}

/** The body of the board's POST /layout (#532): the alignment and, when there are any, the hall beacons. */
export function layoutBody(fit: ScanFit, beacons: { node: string; xyz_m: unknown }[] | undefined): string {
  // floor_m goes only when the square is on a tier (non-zero): the board's /layout takes the four alignment keys,
  // so a desk on the front floor saves there as it always did.
  const { floor_m, ...flat } = tidyFit(fit)
  const room = floor_m ? { ...flat, floor_m } : flat
  return JSON.stringify(beacons?.length ? { room, hall_beacons: beacons } : { room })
}

/** Saves the alignment and the hall beacons' spots where the page is served from: under `vite` into the repo's
 *  room.json and radio/nodes.json; on the board through its POST /layout, kept on the board; anywhere else, or if
 *  that fails, room.json downloads. */
async function saveAll(fit: ScanFit, beacons: HallBeacons | undefined): Promise<string> {
  const json = `${JSON.stringify(tidyFit(fit), null, 2)}\n`
  const post = (url: string, body: string) => fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  try {
    if (import.meta.env.DEV) {
      const room = await post('/__room-scan', json)
      const hall = beacons ? await post('/__hall-beacons', JSON.stringify(beacons.positions())) : null
      if (room.ok) return `Saved to web/public/models/room.json${hall?.ok ? ' and the beacons to radio/nodes.json' : ''}. board/push-web.sh takes it to the board.`
    } else {
      const res = await post('/layout', layoutBody(fit, beacons?.positions()))
      if (res.ok) return 'Saved on the board. A reload keeps it.'
    }
  } catch {
    // fall through to the download
  }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }))
  a.download = 'room.json'
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  return 'Downloaded room.json. Put it in web/public/models/, then build again.'
}

/** Turns align mode on. With no scan loaded it only says how to make one. */
export function startAlign(view: RoomView, stage: Stage, scan: Scan | null, beacons?: HallBeacons) {
  const panel = document.createElement('div')
  panel.className = 'room-align'
  panel.innerHTML = '<h2>Align the scan</h2><p class="room-align-fit"></p><p class="room-align-beacon"></p><p class="room-align-keys"></p><p class="room-align-status"></p><pre hidden></pre>'
  document.body.append(panel) // over the panels' rail, outside the room's stacking context
  const [fitLine, beaconLine, keys, status, pre] = ['.room-align-fit', '.room-align-beacon', '.room-align-keys', '.room-align-status', 'pre'].map((q) => panel.querySelector<HTMLElement>(q)!)
  view.host.dataset.align = scan ? 'on' : 'no-scan'
  if (!scan) {
    fitLine.textContent = 'No scan loaded.'
    keys.textContent = 'Run npm run scan:prep -- <export.glb> in web/, then reload.'
    return
  }

  keys.innerHTML = 'Arrows move · Q E turn · + − scale<br>[ ] cut height · PgUp PgDn floor<br>Shift for big steps<br>Tab picks a beacon · Esc lets go<br>V view from above · S save'
  fitLine.textContent = describeFit(scan.fit)
  beacons?.startEditing(() => (beaconLine.textContent = beacons.describe()))
  // Desk snapping: only on the desk layout, and only when the build knows the hall's desks.
  let hall: HallDesks | null = null
  let spot: DeskSpot | null = null
  if (STRIP_M) {
    void loadDesks().then((h) => {
      hall = h
      if (h) keys.innerHTML += '<br>D nearest desk · I K rows · J L blocks · U O along it'
    })
  }
  const here = (h: HallDesks): DeskSpot => {
    const [sw, sh] = STRIP_M ?? SIZE_M
    const [x, , z] = toScene([sw / 2, sh, 0]) // the middle of the strip's desk edge
    return spot ?? nearestSpot(h, modelPoint([x, z], scan.fit, scan.box))
  }
  /** Stands the strip at a desk spot. Returns false when there is none (no desk that way). */
  const standAt = (next: DeskSpot | null): boolean => {
    if (!hall || !next) return false
    spot = next
    const fit = deskFit(hall, next, scan.box, tidyFit(scan.fit).cut_m)
    scan.apply(fit)
    fitLine.textContent = `${describeFit(fit)}\n${deskName(next.desk)}`
    status.textContent = ''
    return true
  }
  const deskKey = (key: string, shift: boolean): boolean => {
    if (!hall) return false
    const k = key.toLowerCase()
    const step: Record<string, DeskStep> = { i: 'north', k: 'south', j: 'west', l: 'east' }
    if (k === 'd') return standAt(here(hall))
    if (step[k]) return standAt(stepDesk(hall, here(hall), step[k])) || true // no desk that way: stay
    if (k === 'u' || k === 'o') return standAt(slideDesk(here(hall), (k === 'o' ? 1 : -1) * (shift ? 0.5 : 0.1)))
    return false
  }
  drawOnTop(stage.group, stage.drawnRoom)
  view.requestRender()
  let top = false

  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return
    if ((event.target as HTMLElement | null)?.closest?.('input,select,textarea,[contenteditable]')) return
    const key = event.key
    if (key === 'v' || key === 'V') {
      top = !top
      view.setShot(top ? topShot() : roomShot())
    } else if (key === 's' || key === 'S') {
      const json = `${JSON.stringify(tidyFit(scan.fit), null, 2)}\n`
      pre.textContent = json
      pre.hidden = false
      status.textContent = 'Saving…'
      void saveAll(scan.fit, beacons).then((said) => (status.textContent = said))
    } else if (key === 'Tab' && beacons) {
      beacons.cycle()
    } else if (key === 'Escape' && beacons?.selected) {
      beacons.select(null)
    } else if (beacons?.selected && key.startsWith('Arrow')) {
      const step = event.shiftKey ? 1 : 0.1
      const [dx, dy] = { ArrowRight: [step, 0], ArrowLeft: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[key] ?? [0, 0]
      beacons.nudge(dx, dy)
    } else if (deskKey(key, event.shiftKey)) {
      // handled: the strip stands at a desk
    } else {
      const fit = nudge(scan.fit, key, event.shiftKey)
      if (!fit) return
      spot = null // moved by hand: no longer at a desk
      scan.apply(fit)
      fitLine.textContent = describeFit(fit)
      status.textContent = ''
    }
    event.preventDefault() // the arrows would scroll the page
  })
}
