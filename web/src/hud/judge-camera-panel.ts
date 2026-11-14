import type { StateMsg } from '../room/contract'
export function cameraLine(state: StateMsg | null) {
  if (!state) return ''
  if (state.cam === 'off') return 'Camera unplugged · radio only'
  if (state.cam === 'stalled') return 'Camera stalled · radio only'
  const teacher = state.teacher
  return 'Camera on · teaching the radio' + (teacher?.present ? ` · camera says zone ${teacher.zone}${state.pred?.zone === teacher.zone ? ' · agrees' : ''}` : '')
}
export function mountPanel(root: HTMLElement) {
  root.innerHTML = '<p data-testid="camera-line"></p><p data-testid="camera-unplug" hidden>Camera unplugged · Radio alone is tracking the room</p>'
  const line = root.firstElementChild as HTMLElement
  const unplug = root.lastElementChild as HTMLElement
  let previous: StateMsg['cam'] | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  return {
    update(state: StateMsg | null, stale: boolean) {
      root.hidden = stale || !state
      line.textContent = cameraLine(state)
      line.style.color = state?.cam === 'off' || (state?.cam === 'on' && state.teacher?.present && state.teacher.zone === state.pred?.zone) ? 'var(--action)' : 'var(--text-2)'
      if (previous === 'on' && state?.cam === 'off' && !stale) {
        clearTimeout(timer)
        unplug.hidden = false
        timer = setTimeout(() => { unplug.hidden = true }, 8000)
      }
      if (stale || state?.cam !== 'off') unplug.hidden = true
      previous = state?.cam
    },
    dispose() { clearTimeout(timer) },
  }
}
