import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { changingText } from './changing-text'
import './arrival.css'
import { judgeMoment } from './judge-moment'
import { zonePlace } from './layout'

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
/** "Someone passed by" stays this long. */
export const PASSED_BY_MS = 5000

/** Under "Found you.": "0 cameras" only when the camera is known to be unplugged (#651). When the camera watcher
 *  has gone quiet the board says unknown, and the card says only what is true either way: "By radio." */
export function foundLine(cam: string): string {
  return cam === 'off' ? '0 cameras' : cam === 'on' ? 'Camera teaching' : cam === 'stalled' ? 'Camera stalled' : 'By radio.'
}

export function mountArrival(host: HTMLElement, feed: Feed | null, operator: HTMLElement) {
  const view = document.createElement('section')
  view.className = 'hud-arrival'
  view.setAttribute('aria-label', 'Arrival')
  view.innerHTML = `<header><span>Radio Sight</span><span data-testid="arrival-source"></span></header>
    <div class="arrival-message" aria-live="polite"><h1 data-testid="arrival-title"></h1><p data-testid="arrival-detail"></p><p class="arrival-passed" data-testid="arrival-passed"></p></div>
    <footer><span>Taught by a camera. Runs without one.</span><span data-testid="visitor-count">Visitor 0</span></footer>`
  document.body.append(view)
  const title = changingText(view.querySelector('h1')!)
  const detail = changingText(view.querySelector('.arrival-message p')!)
  const passed = changingText(view.querySelector<HTMLElement>('.arrival-passed')!)
  const counter = view.querySelector('[data-testid="visitor-count"]')!
  const source = view.querySelector('[data-testid="arrival-source"]')!
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
  let hold: ReturnType<typeof setTimeout> | undefined
  let fade: Animation[] | undefined
  let phase: ArrivalPhase | undefined
  let phaseCut = false
  let presentSince: number | null = null
  let presentTimer: ReturnType<typeof setTimeout> | undefined
  let passedBy = ''
  let passedTimer: ReturnType<typeof setTimeout> | undefined
  const seen = new Set<string>()
  const cancelHold = () => { clearTimeout(hold); hold = undefined; fade?.forEach(animation => animation.cancel()); fade = undefined }
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
    if (!view.hidden && !matchMedia('(prefers-reduced-motion: reduce)').matches) host.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140, delay: 40, fill: 'backwards' })
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
    const here = !stale && !!state?.pred?.present && state.pred.kind === 'person'
    if (!here) { presentSince = null; clearTimeout(presentTimer); presentTimer = undefined }
    else presentSince ??= performance.now()
    arm.textContent = state?.armed ? 'Disarm space' : 'Arm space'
    arm.disabled = !feed || stale
    source.textContent = state?.src === 'sim' ? 'SIM' : state?.src === 'replay' ? 'REPLAY' : state?.links.some(link => (link.rate_hz ?? 0) > 0) ? 'LIVE' : 'NO RADIO'
    if (!state || stale) { cancelHold(); show('No data', 'Waiting for the room signal.'); return }
    if (state.armed && state.tamper?.length) { cancelHold(); close(true); return }
    if (state.health.status === 'blind') { cancelHold(); show('Sensor blind', 'A radio link stopped.'); return }
    // Once the visitor has been found, a dead zone (advice, the router moved) is the main screen's moment.
    if (complete && !state.armed && (state.advice || state.router !== 'S-home')) { cancelHold(); close(); return }
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
    const waited = presentSince === null ? 0 : performance.now() - presentSince
    if (here && waited < FOUND_AFTER_MS && !hold) presentTimer ??= setTimeout(() => { presentTimer = undefined; render() }, FOUND_AFTER_MS - waited)
    if (here && (waited >= FOUND_AFTER_MS || hold)) {
      // The words hold, then the card fades as the room flies from the hall down to the floor.
      show('Found you.', foundLine(state.cam), false, fade ? 'found' : 'waiting')
      if (!hold) hold = setTimeout(() => {
        if (view.hidden) return
        announce('found')
        // Only the words fade. The rail behind them keeps the page colour, so nothing shows through half-way.
        fade = [...view.children].map(part => part.animate([{ opacity: 1 }, { opacity: 0 }], { duration: FOUND_FADE_MS, easing: 'cubic-bezier(0.4, 0, 0.2, 1)', fill: 'forwards' }))
        hold = setTimeout(() => { complete = true; cancelHold(); render() }, FOUND_FADE_MS)
      }, FOUND_HOLD_MS)
      return
    }
    cancelHold()
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
    if (event.kind === 'reset') { complete = false; cancelHold() }
    render()
  })
  const visibility = new MutationObserver(render)
  visibility.observe(operator, { attributes: true, attributeFilter: ['hidden'] })
  visibility.observe(document.documentElement, { attributes: true, attributeFilter: ['data-hud-replay'] })
  render()
  return () => { cancelHold(); clearTimeout(presentTimer); clearTimeout(passedTimer); passed.dispose(); unsubscribe?.(); offEvents?.(); visibility.disconnect(); title.dispose(); detail.dispose(); arm.remove(); skip.remove(); view.remove(); announce('closed'); host.inert = false; host.removeAttribute('aria-hidden') }
}
