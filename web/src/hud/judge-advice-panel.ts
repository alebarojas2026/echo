import { changingText } from './changing-text'
import type { StateMsg } from '../room/contract'

export function adviceResult(state: StateMsg | null, stale: boolean) {
  const advice = !stale ? state?.advice : null
  if (!advice) return null
  const measured = advice.before_dbm != null && advice.after_dbm != null
  const moved = state!.router === advice.to_spot
  const delta = measured ? advice.after_dbm! - advice.before_dbm! : null
  const gain = delta == null ? '' : `${delta < 0 ? '−' : '+'}${Math.abs(delta).toFixed(1)} dB ${delta < 0 ? 'weaker' : 'stronger'}`
  return {
    text: moved ? measured ? gain : 'Measuring…' : advice.text,
    before: advice.before_dbm, after: advice.after_dbm, positive: moved && delta != null && delta > 0,
  }
}
export function mountPanel(root: HTMLElement) {
  root.innerHTML = '<p data-testid="advice-text"></p><p>Before <span data-testid="before-dbm"></span></p><p>After <span data-testid="after-dbm"></span></p>'
  const title = root.querySelector<HTMLElement>('[data-testid="advice-text"]')!
  const text = changingText(title)
  const number = (value: number | null) => value == null ? '__' : `${String(value).replace('-', '−')} dBm`
  return {
    update(state: StateMsg | null, stale: boolean) {
      const advice = adviceResult(state, stale)
      root.hidden = !advice
      if (!advice) return
      text.set(advice.text)
      title.style.color = advice.positive ? 'var(--action)' : 'var(--text)'
      for (const key of ['before', 'after'] as const) {
        const field = root.querySelector<HTMLElement>(`[data-testid="${key}-dbm"]`)!
        field.textContent = number(advice[key])
        field.style.whiteSpace = 'nowrap'
      }
    },
    dispose() { text.dispose() },
  }
}
