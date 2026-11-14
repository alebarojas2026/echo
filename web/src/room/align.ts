import type { Material, Object3D } from 'three'
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
//   V       straight-down view, or back to the normal one
//   S       save room.json

const STEP_M = 0.02
const BIG_STEP_M = 0.1
const TURN_DEG = 1
const BIG_TURN_DEG = 15
const SCALE_STEP = 1.01
const CUT_STEP_M = 0.05
const MIN_CUT_M = 0.2

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
  }
  return null
}

/** Two lines a person can read off the screen: where, then how. */
export function describeFit(fit: ScanFit): string {
  const f = tidyFit(fit)
  const signed = (v: number, places: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(places)}`
  const where = `East ${signed(f.offset_m[0], 2)} m · North ${signed(f.offset_m[1], 2)} m`
  return `${where}\nTurn ${signed(f.yaw_deg, 1)}° · Scale ${f.scale.toFixed(3)} · Cut ${f.cut_m.toFixed(2)} m`
}

/** Draws everything under `root` except `skip` over whatever is in front of it (the scan). */
function drawOnTop(root: Object3D, skip: Object3D) {
  if (root === skip) return
  const material = (root as Object3D & { material?: Material | Material[] }).material
  for (const m of material ? [material].flat() : []) m.depthTest = false
  if (material) root.renderOrder = 10
  for (const child of root.children) drawOnTop(child, skip)
}

/** Saves under `vite` straight to web/public/models/room.json; anywhere else, downloads room.json. */
async function save(json: string): Promise<string> {
  if (import.meta.env.DEV) {
    try {
      const res = await fetch('/__room-scan', { method: 'POST', headers: { 'content-type': 'application/json' }, body: json })
      if (res.ok) return 'Saved to web/public/models/room.json. board/push-web.sh takes it to the board.'
    } catch {
      // fall through to the download
    }
  }
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([json], { type: 'application/json' }))
  a.download = 'room.json'
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  return 'Downloaded room.json. Put it in web/public/models/, then build again.'
}

/** Turns align mode on. With no scan loaded it only says how to make one. */
export function startAlign(view: RoomView, stage: Stage, scan: Scan | null) {
  const panel = document.createElement('div')
  panel.className = 'room-align'
  panel.innerHTML = '<h2>Align the scan</h2><p class="room-align-fit"></p><p class="room-align-keys"></p><p class="room-align-status"></p><pre hidden></pre>'
  document.body.append(panel) // over the panels' rail, outside the room's stacking context
  const [fitLine, keys, status, pre] = ['.room-align-fit', '.room-align-keys', '.room-align-status', 'pre'].map((q) => panel.querySelector<HTMLElement>(q)!)
  view.host.dataset.align = scan ? 'on' : 'no-scan'
  if (!scan) {
    fitLine.textContent = 'No scan loaded.'
    keys.textContent = 'Run npm run scan:prep -- <export.glb> in web/, then reload.'
    return
  }

  keys.innerHTML = 'Arrows move · Q E turn · + − scale<br>[ ] cut height · Shift for big steps<br>V view from above · S save'
  fitLine.textContent = describeFit(scan.fit)
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
      void save(json).then((said) => (status.textContent = said))
    } else {
      const fit = nudge(scan.fit, key, event.shiftKey)
      if (!fit) return
      scan.apply(fit)
      fitLine.textContent = describeFit(fit)
      status.textContent = ''
    }
    event.preventDefault() // the arrows would scroll the page
  })
}
