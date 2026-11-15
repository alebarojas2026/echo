import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { changingText } from './changing-text'
import './arrival.css'
import { judgeMoment } from './judge-moment'

type ArrivalState = StateMsg & { armed?: boolean }

// The card is words over the live 3D hall (#552). It tells the room what it is showing, so the room can rest on the
// hall while the card waits and fly down to the floor as the card fades:
//   <html data-hud-arrival> and the window event 'hud:arrival' {state: 'waiting' | 'found' | 'closed'}
export type ArrivalPhase = 'waiting' | 'found' | 'closed'
/** "Found you." holds this long, then the card fades while the room flies down. */
export const FOUND_HOLD_MS = 1200
export const FOUND_FADE_MS = 1800

export function mountArrival(host: HTMLElement, feed: Feed | null, operator: HTMLElement) {
  const view = document.createElement('section')
  view.className = 'hud-arrival'
  view.setAttribute('aria-label', 'Arrival')
  view.innerHTML = `<header><span>Radio Sight</span><span data-testid="arrival-source"></span></header>
    <div class="arrival-message" aria-live="polite"><h1 data-testid="arrival-title"></h1><p data-testid="arrival-detail"></p></div>
    <footer><span>Taught by a camera. Runs without one.</span><span data-testid="visitor-count">Visitor 0</span></footer>`
  document.body.append(view)
  const title = changingText(view.querySelector('h1')!)
  const detail = changingText(view.querySelector('.arrival-message p')!)
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
  const seen = new Set<string>()
  const cancelHold = () => { clearTimeout(hold); hold = undefined; fade?.forEach(animation => animation.cancel()); fade = undefined }
  const announce = (next: ArrivalPhase) => {
    if (next === phase) return
    phase = next
    document.documentElement.dataset.hudArrival = next
    window.dispatchEvent(new CustomEvent('hud:arrival', { detail: { state: next } }))
  }
  const close = () => {
    // The panels come in where the words went out, the way every text change on this screen does.
    if (!view.hidden && !matchMedia('(prefers-reduced-motion: reduce)').matches) host.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140, delay: 40, fill: 'backwards' })
    view.hidden = true
    host.inert = false
    host.removeAttribute('aria-hidden')
    announce('closed')
  }
  const show = (heading: string, line: string, fault = false, next: ArrivalPhase = 'waiting') => {
    view.hidden = !operator.hidden
    announce(view.hidden ? 'closed' : next)
    host.inert = !view.hidden
    host.setAttribute('aria-hidden', String(!view.hidden))
    view.dataset.tone = fault ? 'fault' : ''
    title.set(heading)
    detail.set(line)
  }
  const render = () => {
    arm.textContent = state?.armed ? 'Disarm space' : 'Arm space'
    arm.disabled = !feed || stale
    source.textContent = state?.src === 'sim' ? 'SIM' : state?.src === 'replay' ? 'REPLAY' : state?.links.some(link => (link.rate_hz ?? 0) > 0) ? 'LIVE' : 'NO RADIO'
    if (!state || stale) { cancelHold(); show('No data', 'Waiting for the room signal.'); return }
    if (state.health.status === 'blind') { cancelHold(); show('Sensor blind', 'A radio link stopped.'); return }
    if (!state.pred || state.router !== 'S-home') {
      cancelHold()
      const [heading, line] = judgeMoment(state, false)
      show(heading, state.armed ? 'Armed, but not watching right now.' : line)
      return
    }
    if (state.armed) {
      cancelHold()
      intrusion ||= state.pred.present && state.pred.kind === 'person'
      // An intrusion goes straight to the floor: the words stay, in the fault colour, over the room as it is now.
      show(intrusion ? 'Someone is here.' : 'Armed.', !state.pred ? 'Waiting for a room prediction.' : 'This space should be empty.', intrusion, intrusion ? 'closed' : 'waiting')
      return
    }
    if (complete) { close(); return }
    if (state.pred.present && state.pred.kind === 'person') {
      // The words hold, then the card fades as the room flies from the hall down to the floor.
      show('Found you.', state.cam === 'off' ? '0 cameras' : state.cam === 'on' ? 'Camera teaching' : 'Camera stalled', false, fade ? 'found' : 'waiting')
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
    if (event.kind === 'disarmed' || event.kind === 'reset') {
      intrusion = false
      if (state) state = { ...state, armed: false }
    }
    if (event.kind === 'reset') { complete = false; cancelHold() }
    render()
  })
  const visibility = new MutationObserver(render)
  visibility.observe(operator, { attributes: true, attributeFilter: ['hidden'] })
  render()
  return () => { cancelHold(); unsubscribe?.(); offEvents?.(); visibility.disconnect(); title.dispose(); detail.dispose(); arm.remove(); skip.remove(); view.remove(); announce('closed'); host.inert = false; host.removeAttribute('aria-hidden') }
}
