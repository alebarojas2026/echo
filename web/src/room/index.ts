import './room.css'
import { Beams } from './beams'
import type { Feed } from './feed'
import { startFpsMeter } from './fps'
import { Presence } from './ghost'
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
  const mirror = new Mirror(host)
  const beams = new Beams(view, mirror)
  const xray = new XrayLayer(view, mirror)
  const presence = new Presence(view)
  const spots = new RouterSpots(view)

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
    beams.update(state)
    xray.update(state.xray, state.health?.status === 'blind')
    presence.update(state.pred, state.objects ?? [])
    spots.update(state.router, state.advice)
  })
  return { view, stage }
}
