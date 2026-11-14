import './room.css'
import type { Feed } from './feed'
import { Stage } from './stage'
import { RoomView } from './view'

export interface Room {
  view: RoomView
}

/** Builds the 3D room inside `host` and keeps it in step with the feed. */
export function mountRoom(host: HTMLElement, feed: Feed): Room {
  host.classList.add('room')
  const view = new RoomView(host)
  const stage = new Stage(view)

  let router: string | null = null
  feed.subscribe(({ state }) => {
    if (state && state.router !== router) {
      router = state.router
      stage.placeNodes(router)
    }
  })
  return { view }
}
