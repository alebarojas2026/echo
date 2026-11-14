import './room.css'
import { Beams } from './beams'
import type { Feed } from './feed'
import { startFpsMeter } from './fps'
import { AlertMarks, WaveClock } from './alert'
import { Presence } from './ghost'
import { loadScan } from './scan'
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
  const view = new RoomView(host, viewOptions(params))
  if (params.get('fps') === '1') startFpsMeter(view)
  const stage = new Stage(view)
  void loadScan(view, stage.drawnRoom, params)
  const mirror = new Mirror(host)
  const beams = new Beams(view, mirror)
  const xray = new XrayLayer(view, mirror)
  const presence = new Presence(view)
  const spots = new RouterSpots(view)
  const alertMarks = new AlertMarks(view, stage)
  const wave = new WaveClock()

  let router: string | null = null
  feed.subscribe(({ state, stale }) => {
    // NO DATA: the last state is more than 1 s old. The room greys out and holds still.
    host.classList.toggle('room--stale', stale)
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
    presence.update(state.pred, state.objects ?? [], state.xray)
    stage.markZones(state.pred?.zone_set ?? [])
    spots.update(state.router, state.advice)
  })
  return { view, stage }
}
