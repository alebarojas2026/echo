import { changingText } from './changing-text'
import { zonePlace } from './layout'
import type { StateMsg } from '../room/contract'
export function cameraLine(state: StateMsg | null) {
  if (!state) return ''
  if (state.cam === 'off') return 'Camera unplugged · radio only'
  if (state.cam === 'stalled') return 'Camera stalled · radio only'
  const teacher = state.teacher
  // Two short lines: what the camera is doing, then what it sees, in the same words as the headline ("on the right").
  return 'Camera on · teaching the radio' + (teacher?.present ? `
It sees them ${zonePlace(teacher.zone)}${state.pred?.zone === teacher.zone ? ' · the radio agrees' : ''}` : '')
}
export function mountPanel(root: HTMLElement) {
  root.innerHTML = '<p data-testid="cam-status" style="white-space:pre-line"></p><p data-testid="camera-unplug" hidden>The radio alone is following the room now</p>'
  const line = root.firstElementChild as HTMLElement
  const text = changingText(line)
  const unplug = root.lastElementChild as HTMLElement
  unplug.style.color = 'var(--text-2)'
  let previous: StateMsg['cam'] | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  return {
    update(state: StateMsg | null, stale: boolean) {
      root.hidden = stale || !state
      text.set(cameraLine(state))
      line.style.color = state?.cam === 'off' || (state?.cam === 'on' && state.teacher?.present && state.teacher.zone === state.pred?.zone) ? 'var(--text)' : 'var(--text-2)'
      if (previous === 'on' && state?.cam === 'off' && !stale) {
        clearTimeout(timer)
        unplug.hidden = false
        timer = setTimeout(() => { unplug.hidden = true }, 8000)
      }
      if (stale || state?.cam !== 'off') unplug.hidden = true
      previous = state?.cam
    },
    dispose() { text.dispose(); clearTimeout(timer) },
  }
}
