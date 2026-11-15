import { changingText } from './changing-text'
import { dbm, deadZone } from './dead-zone'
import type { StateMsg } from '../room/contract'
import './dead-zone.css'

// The dead-zone card under the headline (#612): what to do, then the before and after the board measured and the gain.
export function adviceResult(state: StateMsg | null, stale: boolean) {
  const zone = deadZone(state, stale)
  return zone && { text: zone.text, before: zone.before, after: zone.after, positive: zone.step === 'better' }
}
export function mountPanel(root: HTMLElement) {
  root.className = 'dead-zone'
  root.dataset.testid = 'dead-zone'
  root.innerHTML = `<p class="dead-zone-text"><svg viewBox="0 0 40 40" aria-hidden="true"><path d="M33 20H8M18 9 7 20l11 11"/></svg><span data-testid="advice-text"></span></p>
    <dl><div><dt data-testid="before-label">Before</dt><dd data-testid="before-dbm"></dd></div><div data-part="after"><dt>After</dt><dd data-testid="after-dbm"></dd></div></dl>`
  const title = root.querySelector<HTMLElement>('[data-testid="advice-text"]')!
  const field = (id: string) => root.querySelector<HTMLElement>(`[data-testid="${id}"]`)!
  const text = changingText(title)
  return {
    update(state: StateMsg | null, stale: boolean) {
      const zone = deadZone(state, stale)
      root.hidden = !zone
      if (!zone) return
      root.dataset.step = zone.step
      root.dataset.way = String(zone.way)
      text.set(zone.text)
      // Before the move there is one reading, the link as it is now; after it, the pair the board measured.
      field('before-label').textContent = zone.step === 'found' ? 'Wi-Fi now' : 'Before'
      field('before-dbm').textContent = dbm(zone.before)
      field('after-dbm').textContent = dbm(zone.after)
      root.querySelector<HTMLElement>('[data-part="after"]')!.hidden = zone.step === 'found'
    },
    dispose() { text.dispose() },
  }
}
