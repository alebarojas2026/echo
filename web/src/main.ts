import { mountRoom } from './room'
import { createFeed, type Feed } from './room/feed'
import { hostHud, type HudModule } from './room/hud-host'

// The panels live in web/src/hud. They are optional here so the room builds and runs on its own.
const hudIndex = import.meta.glob<HudModule<Feed>>('./hud/index.ts', { eager: true })
const hudState = import.meta.glob<HudModule<Feed>>('./hud/state.ts', { eager: true })

const feed = createFeed()
mountRoom(document.getElementById('room')!, feed)
hostHud(document.getElementById('hud')!, feed, {
  ...Object.values(hudState)[0],
  ...Object.values(hudIndex)[0],
})
