import type { StateMsg } from '../room/contract'

export function cameraLine(state: StateMsg | null, radioSeconds: number | null = null) {
  if (!state) return ''
  if (state.cam === 'off') return radioSeconds === null ? 'Radio only' : `Radio only · ${Math.floor(radioSeconds / 60)}:${String(radioSeconds % 60).padStart(2, '0')}`
  if (state.cam === 'stalled') return 'Camera stalled · radio only'
  if (state.cam !== 'on') return 'Camera status unknown'
  const agrees = state.teacher && state.pred && state.teacher.present === state.pred.present && state.teacher.zone === state.pred.zone
  return agrees ? 'Camera teaching · agrees' : 'Camera teaching'
}
export class RadioOnlyClock {
  private previous: StateMsg['cam'] | undefined
  private start: number | null = null
  reset() { this.previous = undefined; this.start = null }
  update(state: StateMsg) {
    if (state.cam === 'off' && this.previous !== undefined && this.previous !== 'off') this.start = state.t
    if (state.cam !== 'off') this.start = null
    this.previous = state.cam
    return this.start !== null && state.t >= this.start ? Math.floor((state.t - this.start) / 1000) : null
  }
}
export function mountPanel(root: HTMLElement) {
  root.innerHTML = '<p data-testid="cam-status"></p>'
  const line = root.firstElementChild as HTMLElement
  const clock = new RadioOnlyClock()
  return {
    update(state: StateMsg | null, stale: boolean) {
      root.hidden = stale || !state
      if (stale || !state) return
      const text = cameraLine(state, clock.update(state))
      if (line.textContent !== text) line.textContent = text
      line.style.color = state.cam === 'off' || text.endsWith('agrees') ? 'var(--text)' : 'var(--text-2)'
    },
    reset() { clock.reset() },
  }
}
