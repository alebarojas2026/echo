import './room.css'
import { Stage } from './stage'
import { RoomView } from './view'

export interface Room {
  view: RoomView
  stage: Stage
}

/** Builds the 3D room inside `host`. */
export function mountRoom(host: HTMLElement): Room {
  host.classList.add('room')
  const view = new RoomView(host)
  const stage = new Stage(view)
  return { view, stage }
}
