import './room.css'
import { amberDb, Beams } from './beams'
import type { Feed } from './feed'
import { startFpsMeter } from './fps'
import { AlertMarks, WaveClock } from './alert'
import { startAlign } from './align'
import { standAtDefaultDesk } from './desks'
import { HallBeacons } from './devices'
import { HallPaths } from './hall'
import { Fly, HallMarks, cutaway, hallShot, pinnedFraming } from './fly'
import { Presence } from './ghost'
import { HeardNodes } from './heard'
import { Replay, rowAlert, rowPred, secondKind, type HistoryRow, type ReplayFrame } from './replay'
import { NODES, SIZE_M, STRIP_M, deviceAcross } from './frame'
import { DEFAULT_CUT_M, loadScan, type Scan } from './scan'
import { Mirror } from './mirror'
import { RouterSpots } from './spots'
import { Stage } from './stage'
import { RoomView, inSituShot, viewOptions } from './view'
import { XrayLayer } from './xray'

/** What the band across the room says while mock data plays. */
export const SIM_WORDS = 'Simulated data'

export interface Room {
  view: RoomView
  stage: Stage
}

/** What the room says when the browser gives it no 3D context. The text column runs on the feed alone. */
export const NO_3D_WORDS = ['3D view unavailable', 'The radio keeps working.'] as const

/** The room's notice: a heading and one line over the room, hidden while the heading is empty. */
function addNotice(host: HTMLElement): (title: string, line: string) => void {
  const notice = document.createElement('div')
  notice.className = 'room-notice'
  notice.setAttribute('role', 'status')
  const title = document.createElement('h2')
  const line = document.createElement('p')
  notice.append(title, line)
  notice.hidden = true
  host.append(notice)
  return (t, l) => {
    notice.hidden = !t
    title.textContent = t
    line.textContent = l
  }
}

/** Builds the 3D room inside `host` and keeps it in step with the feed. Returns null when the 3D view can't start
 *  (no WebGL context: battery saver, a driver hiccup, a remote display); the room then says so in words. */
export function mountRoom(host: HTMLElement, feed: Feed, params = new URLSearchParams(location.search)): Room | null {
  host.classList.add('room')
  // Mock data says so in plain words across the room, the whole time it plays (#642). The room starts below the
  // band, so nothing is ever drawn under it.
  if (feed.source === 'mock') {
    host.classList.add('room--sim')
    const band = document.createElement('div')
    band.className = 'room-sim'
    band.setAttribute('role', 'status')
    band.textContent = SIM_WORDS
    document.body.append(band)
  }
  const options = viewOptions(params)
  let view: RoomView
  try {
    view = new RoomView(host, options)
  } catch (err) {
    // Never an empty two thirds of the screen with no explanation next to a text column that carries on.
    console.error(err)
    host.dataset.room3d = 'unavailable'
    addNotice(host)(...NO_3D_WORDS)
    return null
  }
  host.dataset.quality = options.quality
  if (params.get('fps') === '1') startFpsMeter(view)
  const stage = new Stage(view)
  const scan = loadScan(view, stage.drawnRoom, params, options.quality).then(standAtDefaultDesk)
  const mirror = new Mirror(host)
  const beams = new Beams(view, mirror, amberDb(params))
  const xray = new XrayLayer(view, mirror)
  const presence = new Presence(view)
  const hallBeacons = new HallBeacons(view)
  const hallPaths = new HallPaths(view)

  // The hall and the square (fly.ts). While the camera is wide the labels fade out; the hall marks take over.
  // The desk inside the hall model, once it has loaded: the close view is in situ there (below).
  let situ: Scan | null = null
  const fly = new Fly(view, pinnedFraming(params), (wide) => {
    view.labelLayer.style.opacity = String(Math.max(0, 1 - wide * 4))
    // In situ, the desk run between the camera and the strip turns see-through as the camera comes in, and solid
    // again on the way out, so the whole hall never shows a gap.
    situ?.ghost(cutaway(wide))
  })
  new HallMarks(view, fly, () => presence.standing())
  if (params.get('align') === '1') {
    // ?align=1: line the scan up with the square by eye and save room.json (align.ts). The camera stays put.
    void scan.then((s) => startAlign(view, stage, s, hallBeacons))
  } else {
    void scan.then((s) => {
      if (!s) return
      // The desk inside the hall model: one world, one scale. The person is drawn at true size and the close view
      // is in situ, at our desk among the real rows.
      if (STRIP_M) {
        situ = s
        // Every device stands on what the hall really has under it, wherever nodes.json puts it.
        const [fw, fh] = SIZE_M
        stage.setGround((x, y, z) => s.under(x - fw / 2, fh / 2 - y, z))
        presence.setTrueSize(true)
        fly.setClose(inSituShot)
      }
      fly.setHall(hallShot(s.bounds(), s.fit.cut_m ?? DEFAULT_CUT_M, s.fit.yaw_deg ?? 0))
    })
    feed.onEvent((event) => event.kind === 'reset' && fly.reset())
    // The arrival screen (#552): while the HUD says "Nobody is here." the live hall shows under its words, dimmed
    // and drifting; "found" (or "closed") lifts the dim and flies down to the floor. The HUD sends window event
    // 'hud:arrival' {state: 'waiting' | 'found' | 'closed'} and keeps the latest on <html data-hud-arrival>, so a
    // state set before the room was ready still counts. With neither, the room flies down on load as before.
    const arrival = (state: unknown) => {
      if (state !== 'waiting' && state !== 'found' && state !== 'closed') return
      host.classList.toggle('room--arrival', state === 'waiting')
      host.dataset.arrival = state
      if (state === 'waiting') fly.hold()
      else fly.arrive()
    }
    window.addEventListener('hud:arrival', (e) => arrival((e as CustomEvent<{ state?: string }>).detail?.state))
    arrival(document.documentElement.dataset.hudArrival)
    document.addEventListener('keydown', (event) => {
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey) return
      if ((event.target as HTMLElement | null)?.closest?.('input,select,textarea,[contenteditable]')) return
      if (event.key === 'h' || event.key === 'H') fly.toggle()
    })
  }
  const spots = new RouterSpots(view)
  const alertMarks = new AlertMarks(view)
  const wave = new WaveClock()

  // NO DATA and SENSOR BLIND are different states (contract section 6), and each is said in words.
  const say = addNotice(host)

  // Replay (replay.ts, #537): recorded seconds drive the figure, zone and alert tints; devices and links stay live.
  // The figure's holds run on the replay's own clock, kept ahead of real time so it only moves forward.
  let replayBase = 0
  const showRecorded = (f: ReplayFrame) => {
    const { row } = f.second
    const kind = secondKind(f.second)
    host.dataset.replay = 'on'
    host.dataset.replayT = String(f.second.t)
    host.classList.remove('room--stale')
    host.classList.toggle('room--norecord', kind !== 'record')
    if (kind === 'none') say('No record', 'Nothing was saved for this second.')
    else if (kind === 'unknown') say('Sensor did not know', 'The radio could not tell at this moment.')
    else say('', '')
    presence.wave = false
    beams.setWave(null)
    alertMarks.update(rowAlert(row))
    stage.setTamper(row?.tamper ?? [])
    xray.update(null, false)
    window.dispatchEvent(new CustomEvent('room:replay-frame', { detail: { t: f.second.t, index: f.index, count: f.count, kind } }))
    view.requestRender()
  }
  const replay = new Replay(showRecorded, (reason) => {
    // Back to live: the figure starts fresh where live puts it, and the next state redraws the rest.
    presence.clear()
    host.classList.remove('room--norecord')
    host.dataset.replay = ''
    say('', '')
    window.dispatchEvent(new CustomEvent('room:replay-end', { detail: { reason } }))
    view.requestRender()
  })
  // The figure and the zone names are refreshed every frame on the replay clock, so their holds (200 ms) pass at
  // the replay's speed instead of waiting for the next recorded second.
  view.addAnimator((dt) => {
    const busy = replay.step(dt)
    const now = replay.now
    if (now) {
      presence.update(rowPred(now.second.row), [], null, replayBase + now.clockMs)
      stage.markZones(presence.shownZones(), rowAlert(now.second.row)?.zone ?? null)
    }
    return busy
  })
  window.addEventListener('room:replay', (e) => {
    const detail = (e as CustomEvent<{ rows?: HistoryRow[]; speed?: number }>).detail ?? {}
    replayBase = performance.now()
    presence.clear(replayBase) // the figure starts fresh, in place, with the first recorded second
    replay.play(detail.rows ?? [], detail.speed)
    view.requestRender()
  })
  window.addEventListener('room:live', () => replay.stop('live'))

  let router: string | null = null
  const heard = new HeardNodes()
  feed.subscribe(({ state, stale }) => {
    // NO DATA: the last state is more than 1 s old. The room greys out and holds still (not while replaying).
    if (!replay.playing) {
      host.classList.toggle('room--stale', stale)
      if (stale) say('No data', 'The feed has paused. Nothing here is current.')
      else if (state?.health?.status === 'blind') say('Sensor blind', 'A radio link failed, so predictions pause.')
      else say('', '')
    }
    host.dataset.feed = stale ? 'stale' : 'live'
    if (stale || !state) return
    // Devices are drawn only while the board hears them (heard.ts).
    stage.setHearing(heard.update(Object.keys(NODES), state.links, performance.now()))
    hallBeacons.update(state.hall)
    hallPaths.update(state.hall, state.router)
    if (state.router !== router) {
      router = state.router
      stage.placeNodes(router)
    }
    beams.update(state)
    spots.update(state.router, state.advice)
    if (replay.playing) return // the person, zones and alert come from the recording until it hands back
    stage.setTamper(state.tamper ?? [])
    // A wave check-in shows for 6 s: its link goes green and wide, and the ghost says "Wave seen".
    const waving = wave.update(state.checkin, performance.now())
    host.dataset.checkin = waving ? '1' : ''
    beams.setWave(waving ? wave.link : null)
    presence.wave = waving
    alertMarks.update(state.alert)
    // The advice's words sit just south of the square, where the X-ray caption goes: one at a time.
    // In situ the aisle in front of the strip is the next row's desk: the X-ray's caption has no floor to sit on.
    xray.update(state.xray, state.health?.status === 'blind', spots.tagShown || situ !== null || deviceAcross())
    presence.update(state.pred, state.objects ?? [], state.xray)
    // Zone names follow the zones the figure shows (held), so one wrong decision never flashes a name.
    stage.markZones(presence.shownZones(), state.alert?.state === 'check_on' ? state.alert.zone : null)
  })
  return { view, stage }
}
