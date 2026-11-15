import type { StateMsg } from '../room/contract'
import { LessonProgress } from './lesson'
import './lesson.css'

export function mountPanel(root: HTMLElement) {
  root.className = 'lesson-progress'
  root.hidden = true
  root.innerHTML = '<p data-testid="lesson-status"></p><div class="lesson-signal"><p data-testid="lesson-agreement"></p><div class="lesson-bar" role="progressbar" aria-label="Radio agreement" aria-valuemin="0" aria-valuemax="100"><span></span></div></div>'
  const status = root.querySelector<HTMLElement>('[data-testid="lesson-status"]')!
  const agreement = root.querySelector<HTMLElement>('[data-testid="lesson-agreement"]')!
  const signal = root.querySelector<HTMLElement>('.lesson-signal')!
  const bar = root.querySelector<HTMLElement>('.lesson-bar')!
  const progress = new LessonProgress()
  let state: StateMsg | null = null, stale = true
  const paint = () => {
    const next = progress.update(state, stale)
    root.hidden = !next
    if (!next) return
    if (status.textContent !== next.line) status.textContent = next.line
    if (agreement.textContent !== next.agreement) agreement.textContent = next.agreement
    signal.style.visibility = next.ratio === null ? 'hidden' : 'visible'
    bar.setAttribute('aria-valuenow', String(Math.round((next.ratio ?? 0) * 100)))
    bar.firstElementChild!.setAttribute('style', `transform:scaleX(${next.ratio ?? 0})`)
  }
  const timer = setInterval(paint, 1000)
  return { update(next: StateMsg | null, isStale: boolean) { state = next; stale = isStale; paint() }, dispose() { clearInterval(timer) } }
}
