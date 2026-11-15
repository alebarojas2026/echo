import type { StateMsg } from '../room/contract'
import './stillness.css'
import { zonePlace } from './layout'
import { zoneName } from './judge-moment'

export function stillness(state: StateMsg | null, stale: boolean) {
  if (!state || stale || state.health.status === 'blind') return { text: '', tone: '', progress: 0, detail: '' }
  const alert = state.alert
  if (alert?.state === 'check_on') return { text: `No movement ${zonePlace(alert.zone)} for ${alert.limit_s ?? '__'} s`, tone: 'fault', progress: 1, detail: alert.still_s == null ? '__' : `Still for ${Math.floor(alert.still_s)} s` }
  const age = state.checkin ? state.t - state.checkin.t : Infinity
  if (age >= 0 && age <= 6000) return { text: 'Wave seen', tone: 'action', progress: 0, detail: 'Check-in received' }
  if (alert?.state !== 'counting') return { text: '', tone: '', progress: 0, detail: '' }
  const seconds = alert.still_s == null ? '__' : Math.floor(alert.still_s)
  const limit = alert.limit_s
  return { text: `Still for ${seconds} s of ${limit ?? '__'}`, tone: 'person', progress: limit && alert.still_s != null ? Math.min(1, Math.max(0, Math.floor(alert.still_s) / limit)) : 0, detail: '' }
}

export function mountPanel(root: HTMLElement) {
  root.className = 'stillness-card'
  root.innerHTML = '<p data-testid="alert-banner"></p><p data-testid="checkin-toast"></p><p data-testid="alert-zone"></p><p data-testid="alert-seconds"></p><div class="stillness-track"><span></span></div>'
  const text = root.querySelector<HTMLElement>('[data-testid="alert-banner"]')!
  const wave = root.querySelector<HTMLElement>('[data-testid="checkin-toast"]')!
  const detail = root.querySelector<HTMLElement>('[data-testid="alert-seconds"]')!
  const zone = root.querySelector<HTMLElement>('[data-testid="alert-zone"]')!
  const bar = root.querySelector<HTMLElement>('.stillness-track span')!
  let previous = ''
  let revision = 0
  const animations = new Set<Animation>()
  const animate = (frames: Keyframe[], options: KeyframeAnimationOptions) => {
    const animation = root.animate(frames, options)
    animations.add(animation)
    return animation.finished.catch(() => {}).finally(() => animations.delete(animation))
  }
  return {
    update(state: StateMsg | null, stale: boolean) {
      const value = stillness(state, stale)
      bar.style.transform = `scaleX(${value.progress})`
      detail.textContent = value.detail
      zone.textContent = value.tone === 'fault' && state?.alert?.zone != null ? zoneName(state.alert.zone) : ''
      const identity = value.tone
      const apply = () => {
        root.hidden = !value.text
        root.dataset.tone = value.tone
        text.textContent = value.tone === 'action' ? '' : value.text
        wave.textContent = value.tone === 'action' ? value.text : ''
      }
      if (identity === previous) { apply(); return }
      previous = identity
      const current = ++revision
      animations.forEach(animation => animation.cancel())
      if (matchMedia('(prefers-reduced-motion: reduce)').matches || root.hidden) { apply(); return }
      void animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, fill: 'forwards' }).then(async () => {
        if (current !== revision) return
        apply()
        await animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 140, delay: 40, fill: 'both' })
        if (current === revision) root.getAnimations().forEach(animation => animation.cancel())
      })
    },
    dispose() { revision++; animations.forEach(animation => animation.cancel()); root.getAnimations().forEach(animation => animation.cancel()) },
  }
}
