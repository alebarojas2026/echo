import './room.css'
import type { Feed } from './feed'
import { Stage } from './stage'
import { RoomView } from './view'

export interface Room {
  view: RoomView
  stage: Stage
}

/** Builds the 3D room inside `host` and keeps it in step with the feed. */
export function mountRoom(host: HTMLElement, feed: Feed): Room {
  host.classList.add('room')
  const view = new RoomView(host)
  const stage = new Stage(view)

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
  })
  return { view, stage }
}
