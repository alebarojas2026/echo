import { HOME_SPOT, ROUTER_SPOTS } from '../room/frame'

export function routerWords(id: string) {
  if (id === HOME_SPOT) return 'Router at home'
  const home = ROUTER_SPOTS[HOME_SPOT]
  const spot = ROUTER_SPOTS[id]
  if (!home || !spot) return 'Router location unavailable'
  const dx = spot[0] - home[0], dy = spot[1] - home[1]
  const direction = Math.abs(dx) >= Math.abs(dy) ? dx < 0 ? 'west' : 'east' : dy < 0 ? 'south' : 'north'
  return `Router ${Math.round(Math.hypot(dx, dy) * 100)} cm ${direction}`
}
