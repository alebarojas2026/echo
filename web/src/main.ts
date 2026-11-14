import { mountRoom } from './room'
import { createFeed } from './room/feed'
import { hostHud, type HudModule } from './room/hud-host'
import { loadLayout } from './room/layout'

// The panels live in web/src/hud. They are optional here so the room builds and runs on its own.
const hudIndex = import.meta.glob<HudModule>('./hud/index.ts', { eager: true })
const hudState = import.meta.glob<HudModule>('./hud/state.ts', { eager: true })

const feed = createFeed()
const roomEl = document.getElementById('room')!

// The room waits (at most 2 s) for the real layout; the panels don't need it.
loadLayout().then((layout) => {
  roomEl.dataset.layout = layout
  mountRoom(roomEl, feed)
})
hostHud(document.getElementById('hud')!, feed, {
  ...Object.values(hudState)[0],
  ...Object.values(hudIndex)[0],
})
