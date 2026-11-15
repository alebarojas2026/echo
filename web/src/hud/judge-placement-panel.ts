import type { StateMsg } from '../room/contract'
import { hudLayout, linkName } from './layout'
import { PlacementCheck, measured, usable } from './placement-check'
import './placement.css'

export function mountPanel(root: HTMLElement) {
  const check = new PlacementCheck()
  root.className = 'placement-check'
  root.dataset.testid = 'placement-check'
  root.hidden = true
  root.innerHTML = `<h2>Placement check</h2><p>Leave the space empty for 5 seconds, then step into the spot to check its links.</p>
    <button type="button" data-testid="placement-measure">Measure empty-room wobble</button>
    <p role="status" data-testid="placement-status"></p><div class="placement-links"></div>
    <p>Tick: drop above the sampled empty-room peak and mean + 3 standard deviations. This check does not change the board baseline or model.</p>`
  const button = root.querySelector<HTMLButtonElement>('button')!
  const status = root.querySelector<HTMLElement>('[role="status"]')!
  const list = root.querySelector<HTMLElement>('.placement-links')!
  let latest: StateMsg | null = null, isStale = true, key = '', numbersAt = -Infinity
  const rows = new Map<string, HTMLElement>()
  const update = (state: StateMsg | null, stale: boolean) => {
    latest = state; isStale = stale
    const operator = root.closest('.judge')?.querySelector('.hud-operator')
    if (!operator) return
    if (root.parentElement !== operator) operator.querySelector('h2')!.after(root)
    root.hidden = false
    check.update(state, stale, JSON.stringify([hudLayout.nodes, hudLayout.links]))
    const live = !!state && !stale && state.src !== 'replay'
    button.disabled = !live || check.capturing
    status.textContent = !live ? 'Waiting for live readings' : check.capturing ? `Measuring empty room · ${Math.floor(check.elapsed / 1000)} of 5 s` : 'Step into the spot. Links that see the drop get a tick.'
    const links = state?.links ?? []
    const nextKey = JSON.stringify(links.map(link => [link.id, linkName(link.id)]))
    if (nextKey !== key) {
      key = nextKey; rows.clear(); list.replaceChildren()
      for (const link of links) {
        const row = document.createElement('div')
        row.className = 'placement-link'; row.dataset.testid = 'placement-link'; row.dataset.link = link.id
        row.innerHTML = '<h3></h3><p><span data-rate></span><span data-drop></span></p><div class="placement-track"><span></span><i></i></div><p class="placement-result"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg><span></span></p>'
        row.querySelector('h3')!.textContent = linkName(link.id)
        list.append(row); rows.set(link.id, row)
      }
      numbersAt = -Infinity
    }
    const now = performance.now(), numbers = now - numbersAt >= 1000
    if (numbers) numbersAt = now
    for (const link of links) {
      const row = rows.get(link.id)!
      const valid = live && usable(link), threshold = check.threshold(link)
      const seen = check.seen(link, !live)
      row.dataset.seen = String(seen)
      const signal = valid ? 'ok' : 'missing'
      if (numbers || row.dataset.signal !== signal) {
        row.dataset.signal = signal
        row.querySelector('[data-rate]')!.textContent = `${live && measured(link.rate_hz) ? link.rate_hz.toFixed(1) : '__'} readings/s`
        row.querySelector('[data-drop]')!.textContent = `${valid ? link.drop_db!.toFixed(1) : '__'} dB drop`
      }
      const scale = Math.max(8, threshold ?? 0, valid ? link.drop_db! : 0) * 1.2
      const bar = row.querySelector<HTMLElement>('.placement-track span')!
      bar.style.width = `${valid ? Math.max(0, link.drop_db!) / scale * 100 : 0}%`
      const marker = row.querySelector<HTMLElement>('.placement-track i')!
      marker.hidden = threshold === null
      marker.style.left = `${(threshold ?? 0) / scale * 100}%`
      row.querySelector('.placement-result span')!.textContent = !live ? 'No live reading' : !valid ? 'Reading or baseline missing' : threshold === null ? 'Wobble not measured' : seen ? 'Above empty-room wobble' : 'Within empty-room wobble'
    }
  }
  button.onclick = () => { check.begin(); update(latest, isStale) }
  return { update, reset() { check.reset(); update(latest, isStale) }, dispose() { root.remove() } }
}
