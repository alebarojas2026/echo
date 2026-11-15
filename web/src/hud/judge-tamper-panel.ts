import type { StateMsg } from '../room/contract'
import { HALL_BEACONS, NODES } from '../room/frame'
import './tamper.css'

// The tamper alert (#537, wording #533): while armed, a device that has gone silent is named in plain words, in the
// fault colour, until it is heard again. It sits above everything in the rail, the arrival card included, and it
// shows while the sensor is blind too: that is when it matters.

/** "East beacon", from radio/nodes.json. A hall beacon is named by its letter. Never a raw id. */
export function deviceName(id: string): string {
  const hall = HALL_BEACONS.find((beacon) => beacon.node === id)
  return NODES[id]?.name ?? (hall ? `Hall beacon ${hall.id}` : 'A device')
}

/** "East beacon unplugged while armed", or "" when nothing is silent. */
export function tamperWords(state: StateMsg | null, stale: boolean): string {
  const silent = !stale && state?.tamper?.length ? [...new Set(state.tamper)].map(deviceName) : []
  if (!silent.length) return ''
  const names = silent.length < 3 ? silent.join(' and ') : `${silent.slice(0, -1).join(', ')} and ${silent.at(-1)}`
  return `${names} unplugged while armed`
}

export function mountPanel(root: HTMLElement) {
  const alert = document.createElement('section')
  alert.className = 'tamper-alert'
  alert.dataset.testid = 'tamper-alert'
  alert.setAttribute('role', 'alert')
  alert.hidden = true
  alert.innerHTML = '<p>Tamper alert</p><h2 data-testid="tamper-text"></h2>'
  root.remove()
  document.body.append(alert)
  const text = alert.querySelector('h2')!
  return {
    update(state: StateMsg | null, stale: boolean) {
      const words = tamperWords(state, stale)
      if (words) text.textContent = words
      if (alert.hidden === !words) return
      alert.hidden = !words
      if (words && !matchMedia('(prefers-reduced-motion: reduce)').matches) alert.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140 })
    },
    dispose() { alert.remove() },
  }
}
