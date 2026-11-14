import { mountRoom } from './room'
import { hostHud, type HudModule } from './room/hud-host'

// The panels live in web/src/hud. They are optional here so the room builds and runs on its own.
const hudIndex = import.meta.glob<HudModule>('./hud/index.ts', { eager: true })
const hudState = import.meta.glob<HudModule>('./hud/state.ts', { eager: true })

mountRoom(document.getElementById('room')!)
hostHud(document.getElementById('hud')!, null, {
  ...Object.values(hudState)[0],
  ...Object.values(hudIndex)[0],
})
