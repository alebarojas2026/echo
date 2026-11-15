import type { StateMsg } from '../room/contract'
import { handoff, handoffReady } from './handoff'
import './handoff.css'

export function mountPanel(root: HTMLElement) {
  root.className = 'handoff-strip'
  root.dataset.testid = 'handoff-strip'
  root.innerHTML = '<div class="handoff-heading"><h2 data-testid="handoff-title"></h2><span data-testid="handoff-time"></span></div><div class="handoff-track" aria-hidden="true"><span class="handoff-teaching"></span><span class="handoff-radio"></span><i data-testid="handoff-edge" hidden></i></div><p data-testid="handoff-detail"></p>'
  const title = root.querySelector('h2')!, time = root.querySelector('[data-testid="handoff-time"]')!, detail = root.querySelector('p')!
  const teaching = root.querySelector<HTMLElement>('.handoff-teaching')!, radio = root.querySelector<HTMLElement>('.handoff-radio')!, edge = root.querySelector<HTMLElement>('i')!
  return {
    update(state: StateMsg | null, stale: boolean) {
      root.hidden = state?.src === 'replay' || !handoffReady(state)
      const value = handoff(state, stale)
      root.dataset.phase = value.phase
      if (title.textContent !== value.title) title.textContent = value.title
      if (time.textContent !== value.time) time.textContent = value.time
      if (detail.textContent !== value.detail) detail.textContent = value.detail
      teaching.style.transform = `scaleX(${value.teaching})`
      radio.style.left = `${value.teaching * 100}%`
      radio.style.transform = `scaleX(${value.radio})`
      edge.hidden = !value.edge
      edge.style.left = `${value.teaching * 100}%`
    },
  }
}
