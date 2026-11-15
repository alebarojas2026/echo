import { mountPrivacyLine } from './privacy'
import { sourceWords } from './source-words'
import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { changingText, framesDrawn } from './changing-text'
import './arrival.css'
import { judgeMoment } from './judge-moment'
import { blindSentence } from './health-words'
import { hudLayout, loadHudLayout, zonePlace } from './layout'
import { boardNow } from './board-time'

type ArrivalState = StateMsg & { armed?: boolean }

// The card is words over the live 3D hall (#552). It tells the room what it is showing, so the room can rest on the
// hall while the card waits and fly down to the floor as the card fades:
//   <html data-hud-arrival> and the window event 'hud:arrival' {state: 'waiting' | 'found' | 'closed'}
export type ArrivalPhase = 'waiting' | 'found' | 'closed'
/** "Found you." holds this long, then the card fades while the room flies down. */
export const FOUND_HOLD_MS = 1200
export const FOUND_FADE_MS = 1800
/** Someone has to be there this long before "Found you.", so a person walking past does not flash it (#584). */
export const FOUND_AFTER_MS = 1500
/** One state that does not say "a person is here" inside this long does not start the count again. */
export const FOUND_GAP_MS = 300
/** "Someone passed by" stays this long. */
export const PASSED_BY_MS = 5000

/** Under "Found you.": "0 cameras" only when the camera is known to be unplugged (#651). When the camera watcher
 *  has gone quiet the board says unknown, and the card says only what is true either way: "By radio." */
export function foundLine(cam: string): string {
  return cam === 'off' ? '0 cameras' : cam === 'on' ? 'Camera teaching' : cam === 'stalled' ? 'Camera stalled' : 'By radio.'
}

export type ArrivalStep = 'waiting' | 'found' | 'fading' | 'done'
/** Where the card is, from how long the board has said a person is here (board time, ms; null = nobody).
 *  Nothing else decides it: no timer and no drawn frame, so a page that was in a background tab, asleep or
 *  reconnecting shows the right step on the next state it gets. */
export function arrivalStep(presentMs: number | null): ArrivalStep {
  if (presentMs === null || presentMs < FOUND_AFTER_MS) return 'waiting'
  if (presentMs < FOUND_AFTER_MS + FOUND_HOLD_MS) return 'found'
  return presentMs < FOUND_AFTER_MS + FOUND_HOLD_MS + FOUND_FADE_MS ? 'fading' : 'done'
}

/** Since when (board time) a person has been here without a break longer than FOUND_GAP_MS. */
export class PresentSince {
  private since: number | null = null
  private last = 0
  /** now: board time of this reading, or null when there is none. Returns ms present, or null. */
  update(here: boolean, now: number | null): number | null {
    if (now === null) this.since = null
    else if (here) {
      // A board clock that stepped back (a restart) starts the count again.
      if (this.since === null || now < this.since) this.since = now
      this.last = now
    } else if (this.since !== null && (now - this.last > FOUND_GAP_MS || now < this.last)) this.since = null
    return this.since === null || now === null ? null : now - this.since
  }
  clear() { this.since = null }
}

export function mountArrival(host: HTMLElement, feed: Feed | null, operator: HTMLElement) {
  const view = document.createElement('section')
  view.className = 'hud-arrival'
  view.setAttribute('aria-label', 'Arrival')
  view.innerHTML = `<header><span>Echo</span><span class="judge-claim">No camera. No microphone.</span><span data-testid="arrival-source"></span></header>
    <div class="arrival-message" aria-live="polite"><h1 data-testid="arrival-title"></h1><p data-testid="arrival-detail"></p><p class="arrival-passed" data-testid="arrival-passed"></p></div>
    <footer><span data-testid="arrival-claim"></span><span data-testid="visitor-count">Visitor 0</span></footer>`
  const disposePrivacy = mountPrivacyLine(view)
  view.querySelector('.arrival-message')!.before(view.querySelector('.privacy-line')!)
  document.body.append(view)
  const title = changingText(view.querySelector('h1')!)
  const detail = changingText(view.querySelector('.arrival-message p')!)
  const passed = changingText(view.querySelector<HTMLElement>('.arrival-passed')!)
  const counter = view.querySelector('[data-testid="visitor-count"]')!
  const source = view.querySelector('[data-testid="arrival-source"]')!
  const recent = host.querySelector<HTMLButtonElement>('[data-testid="what-happened"]')
  if (recent) {
    const ask = document.createElement('button')
    ask.type = 'button'; ask.className = 'arrival-ask'; ask.dataset.testid = 'arrival-what-happened'; ask.textContent = 'What happened?'
    ask.onclick = () => recent.click()
    view.querySelector('.arrival-message')!.append(ask)
  }
  const claim = view.querySelector('[data-testid="arrival-claim"]')!
  const arm = document.createElement('button')
  arm.type = 'button'
  arm.textContent = 'Arm space'
  arm.dataset.testid = 'arm-button'
  const skip = document.createElement('button')
  skip.type = 'button'
  skip.textContent = 'Skip the arrival screen'
  skip.dataset.testid = 'skip-arrival'
  operator.prepend(arm, skip)
  let state: ArrivalState | null = null
  let stale = true
  let complete = false
  let intrusion = false
  let wake: ReturnType<typeof setTimeout> | undefined
  let fade: Animation[] | undefined
  let phase: ArrivalPhase | undefined
  let phaseCut = false
  const present = new PresentSince()
  let here = false
  let passedBy = ''
  let passedTimer: ReturnType<typeof setTimeout> | undefined
  const seen = new Set<string>()
  const cancelHold = () => { clearTimeout(wake); wake = undefined; fade?.forEach(animation => animation.cancel()); fade = undefined }
  // cut: an intrusion goes straight to the floor, so the room should jump there instead of flying (#552).
  const announce = (next: ArrivalPhase, cut = false) => {
    if (next === phase && cut === phaseCut) return
    phase = next
    phaseCut = cut
    document.documentElement.dataset.hudArrival = next
    if (cut) document.documentElement.dataset.hudArrivalCut = '1'
    else delete document.documentElement.dataset.hudArrivalCut
    window.dispatchEvent(new CustomEvent('hud:arrival', { detail: cut ? { state: next, cut: true } : { state: next } }))
  }
  // A replay plays on the main screen (#537): the card steps aside for it and comes back when it is over.
  const replaying = () => document.documentElement.dataset.hudReplay === 'on'
  const close = (cut = false) => {
    // The panels come in where the words went out, the way every text change on this screen does.
    if (!view.hidden && framesDrawn() && !matchMedia('(prefers-reduced-motion: reduce)').matches) host.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140, delay: 40, fill: 'backwards' })
    view.hidden = true
    host.inert = false
    host.removeAttribute('aria-hidden')
    announce('closed', cut)
  }
  const show = (heading: string, line: string, fault = false, next: ArrivalPhase = 'waiting', cut = false) => {
    view.hidden = !operator.hidden || replaying()
    announce(view.hidden ? 'closed' : next, cut)
    host.inert = !view.hidden
    host.setAttribute('aria-hidden', String(!view.hidden))
    view.dataset.tone = fault ? 'fault' : ''
    title.set(heading)
    detail.set(line)
    // Small and calm, only while armed and only while nothing louder is on the card.
    passed.set(state?.armed && !fault && !stale ? passedBy : '')
  }
  const render = () => {
    here = !stale && !!state?.pred?.present && state.pred.kind === 'person'
    // The board's clock: the last state's t, carried forward by this page's clock until the next one.
    const presentMs = present.update(here, stale ? null : boardNow(feed?.current() ?? null))
    clearTimeout(wake)
    wake = undefined
    // The one-spot kit has no camera at all; the camera lesson is the other layouts' story.
    claim.textContent = 'A witness that never watches.'
    arm.textContent = state?.armed ? 'Disarm space' : 'Arm space'
    arm.disabled = !feed || stale
    source.textContent = sourceWords(state)
    if (!state || stale) { cancelHold(); show('No data', 'Waiting for the room signal.'); return }
    if (state.armed && state.tamper?.length) { cancelHold(); close(true); return }
    if (state.health.status === 'blind') { cancelHold(); show('Sensor blind', blindSentence(state)); return }
    if (complete && !state.armed) { cancelHold(); close(); return }
    if (!state.pred || state.router !== 'S-home') {
      cancelHold()
      const [heading, line] = judgeMoment(state, false)
      show(heading, state.armed ? 'Armed. Monitoring is paused.' : line)
      return
    }
    if (state.armed) {
      cancelHold()
      // Only the board's intrusion event raises the alarm: it has waited to see the person stay (#584).
      // An intrusion goes straight to the floor: the words stay, in the fault colour, over the room as it is now.
      show(intrusion ? 'Someone is here.' : 'Armed.', !state.pred ? 'Waiting for a room prediction.' : 'This space should be empty.', intrusion, intrusion ? 'closed' : 'waiting', intrusion)
      return
    }
    if (complete) { close(); return }
    const step = arrivalStep(presentMs)
    if (step === 'done') { complete = true; cancelHold(); close(); return }
    if (presentMs !== null) {
      // A wake-up for the next step, for a feed that has gone quiet. Every state message recomputes anyway.
      const next = [FOUND_AFTER_MS, FOUND_AFTER_MS + FOUND_HOLD_MS, FOUND_AFTER_MS + FOUND_HOLD_MS + FOUND_FADE_MS].find(at => at > presentMs)!
      wake = setTimeout(render, next - presentMs)
    }
    if (step === 'found' || step === 'fading') {
      // The words hold, then the card fades as the room flies from the hall down to the floor.
      show('Found you.', hudLayout.zones.length === 1 ? 'By radio.' : foundLine(state.cam), false, step === 'fading' ? 'found' : 'waiting')
      if (step === 'found' || view.hidden) { fade?.forEach(animation => animation.cancel()); fade = undefined; return }
      // Only the words fade. The rail behind them keeps the page colour, so nothing shows through half-way.
      fade ??= [...view.children].filter(part => !part.classList.contains('privacy-line')).map(part => part.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FOUND_FADE_MS, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', fill: 'forwards' }))
      // The fade is as far along as the board's clock says, also after a while with no frames drawn.
      const at = presentMs! - FOUND_AFTER_MS - FOUND_HOLD_MS
      for (const animation of fade) if (Math.abs(Number(animation.currentTime ?? 0) - at) > 150) animation.currentTime = at
      return
    }
    fade?.forEach(animation => animation.cancel())
    fade = undefined
    show(state.pred.kind === 'object' ? 'An object, not a person.' : 'Nobody is here.', 'Step up to the desk.')
  }
  skip.onclick = () => { complete = true; cancelHold(); render() }
  arm.onclick = () => {
    // CONTRACTS.md includes arm before the room command types do.
    feed?.send('arm' as Parameters<Feed['send']>[0], { on: !state?.armed })
  }
  const unsubscribe = feed?.subscribe(snapshot => {
    const next = snapshot.state as ArrivalState | null
    if (state?.armed && next && !next.armed) intrusion = false
    state = next
    stale = snapshot.stale
    render()
  })
  const offEvents = feed?.onEvent(event => {
    if (event.kind === 'enter' && !seen.has(`${event.src}:${event.id}`)) {
      seen.add(`${event.src}:${event.id}`)
      counter.textContent = `Visitor ${seen.size}`
    }
    if (event.kind === 'intrusion') intrusion = true
    if (event.kind === 'passed_by') {
      const zone = typeof event.info.zone === 'number' ? event.info.zone : null
      passedBy = zone === null ? 'Someone passed by' : `Someone passed by ${zonePlace(zone)}`
      clearTimeout(passedTimer)
      passedTimer = setTimeout(() => { passedBy = ''; render() }, PASSED_BY_MS)
    }
    if (event.kind === 'disarmed' || event.kind === 'reset') {
      intrusion = false
      passedBy = ''
      clearTimeout(passedTimer)
      if (state) state = { ...state, armed: false }
    }
    // Between judges: whoever stepped off a moment ago is not greeted again.
    if (event.kind === 'reset') { complete = false; cancelHold(); if (!here) present.clear() }
    render()
  })
  const visibility = new MutationObserver(render)
  visibility.observe(operator, { attributes: true, attributeFilter: ['hidden'] })
  visibility.observe(document.documentElement, { attributes: true, attributeFilter: ['data-hud-replay'] })
  // A tab brought back to the front, or a laptop that woke up: the card is worked out again at once.
  document.addEventListener('visibilitychange', render)
  render()
  void loadHudLayout().then(() => { if (view.isConnected) render() })
  return () => { document.removeEventListener('visibilitychange', render); disposePrivacy(); cancelHold(); clearTimeout(passedTimer); passed.dispose(); unsubscribe?.(); offEvents?.(); visibility.disconnect(); title.dispose(); detail.dispose(); arm.remove(); skip.remove(); view.remove(); announce('closed'); host.inert = false; host.removeAttribute('aria-hidden') }
}
