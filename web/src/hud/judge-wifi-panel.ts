import type { StateMsg } from '../room/contract'
import { wifiLine, wifiLinkId } from './dead-zone'
import { hudLayout } from './layout'
import './dead-zone.css'

// The calm Wi-Fi line (#612): the router's link to the board in a word and one number, always on the main screen.
// It sits on the rule above the signal trace, so the two read as one block of radio readings.
export function mountPanel(root: HTMLElement) {
  const line = document.createElement('p')
  line.className = 'wifi-line'
  line.dataset.testid = 'wifi-line'
  line.innerHTML = '<span>Wi-Fi link · <b data-testid="wifi-word"></b></span><span data-testid="wifi-value"></span>'
  root.replaceWith(line)
  const word = line.querySelector<HTMLElement>('[data-testid="wifi-word"]')!
  const value = line.querySelector<HTMLElement>('[data-testid="wifi-value"]')!
  const place = () => {
    const rail = line.closest('.judge')
    const below = rail?.querySelector(':scope > .signal') ?? rail?.querySelector(':scope > footer')
    if (below && line.nextElementSibling !== below) below.before(line)
  }
  let shownAt = -Infinity
  return {
    update(state: StateMsg | null, stale: boolean) {
      place()
      // A replayed second holds no link readings (the records keep none), so the line steps out with the trace.
      // Where the presence line is this same link, the signal row under it already gives its number: said once,
      // and a person standing in the line is never called a weak link.
      line.hidden = !!(state as { replay?: unknown } | null)?.replay || (!!hudLayout.presence?.line && hudLayout.presence.line === wifiLinkId(state?.advice))
      if (line.hidden) return
      const wifi = wifiLine(state, stale)
      line.setAttribute('aria-label', `Wi-Fi link, ${wifi.ends}`)
      // The number is rewritten four times a second, and at once when the word changes.
      const now = performance.now()
      if (line.dataset.status === wifi.status && now - shownAt < 250) return
      shownAt = now
      line.dataset.status = wifi.status
      word.textContent = wifi.word
      value.textContent = wifi.value
    },
    dispose() { line.remove() },
  }
}
