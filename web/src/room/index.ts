import './room.css'
import { Beams } from './beams'
import type { Feed } from './feed'
import { startFpsMeter } from './fps'
import { AlertMarks, WaveClock } from './alert'
import { startAlign } from './align'
import { Fly, HallMarks, hallShot, pinnedFraming } from './fly'
import { Presence } from './ghost'
import { DEFAULT_CUT_M, loadScan } from './scan'
import { Mirror } from './mirror'
import { RouterSpots } from './spots'
import { Stage } from './stage'
import { RoomView, viewOptions } from './view'
import { XrayLayer } from './xray'

export interface Room {
  view: RoomView
  stage: Stage
}

/** Builds the 3D room inside `host` and keeps it in step with the feed. */
export function mountRoom(host: HTMLElement, feed: Feed, params = new URLSearchParams(location.search)): Room {
  host.classList.add('room')
  const options = viewOptions(params)
  const view = new RoomView(host, options)
  host.dataset.quality = options.quality
  if (params.get('fps') === '1') startFpsMeter(view)
  const stage = new Stage(view)
  const scan = loadScan(view, stage.drawnRoom, params, options.quality)
  const mirror = new Mirror(host)
  const beams = new Beams(view, mirror)
  const xray = new XrayLayer(view, mirror)
  const presence = new Presence(view)

  // The hall and the square (fly.ts). While the camera is wide the labels fade out; the hall marks take over.
  const fly = new Fly(view, pinnedFraming(params), (wide) => {
    view.labelLayer.style.opacity = String(Math.max(0, 1 - wide * 4))
  })
  new HallMarks(view, fly, () => presence.standing())
  if (params.get('align') === '1') {
    // ?align=1: line the scan up with the square by eye and save room.json (align.ts). The camera stays put.
    void scan.then((s) => startAlign(view, stage, s))
  } else {
    void scan.then((s) => s && fly.setHall(hallShot(s.bounds(), s.fit.cut_m ?? DEFAULT_CUT_M)))
    feed.onEvent((event) => event.kind === 'reset' && fly.reset())
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
  const notice = document.createElement('div')
  notice.className = 'room-notice'
  notice.setAttribute('role', 'status')
  notice.innerHTML = '<h2></h2><p></p>'
  notice.hidden = true
  host.append(notice)
  const say = (title: string, line: string) => {
    notice.hidden = !title
    notice.querySelector('h2')!.textContent = title
    notice.querySelector('p')!.textContent = line
  }

  let router: string | null = null
  feed.subscribe(({ state, stale }) => {
    // NO DATA: the last state is more than 1 s old. The room greys out and holds still.
    host.classList.toggle('room--stale', stale)
    if (stale) say('No data', 'The feed has paused. Nothing here is current.')
    else if (state?.health?.status === 'blind') say('Sensor blind', 'A radio link failed, so predictions pause.')
    else say('', '')
    host.dataset.feed = stale ? 'stale' : 'live'
    if (stale || !state) return
    if (state.router !== router) {
      router = state.router
      stage.placeNodes(router)
    }
    // A wave check-in shows for 6 s: its link goes green and wide, and the ghost says "Wave seen".
    const waving = wave.update(state.checkin, performance.now())
    host.dataset.checkin = waving ? '1' : ''
    beams.setWave(waving ? wave.link : null)
    presence.wave = waving
    alertMarks.update(state.alert)
    beams.update(state)
    xray.update(state.xray, state.health?.status === 'blind')
    presence.update(state.pred, state.objects ?? [], state.xray, state.router)
    // Zone names follow the zones the figure shows (held), so one wrong decision never flashes a name.
    stage.markZones(presence.shownZones(), state.alert?.state === 'check_on' ? state.alert.zone : null)
    spots.update(state.router, state.advice)
  })
  return { view, stage }
}
