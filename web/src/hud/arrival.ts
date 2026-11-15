import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { changingText } from './changing-text'
import './arrival.css'
import { judgeMoment } from './judge-moment'

type ArrivalState = StateMsg & { armed?: boolean }

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
  operator.prepend(arm)
  let state: ArrivalState | null = null
  let stale = true
  let complete = false
  let intrusion = false
  let hold: ReturnType<typeof setTimeout> | undefined
  const seen = new Set<string>()
  const cancelHold = () => { clearTimeout(hold); hold = undefined }
  const show = (heading: string, line: string, fault = false) => {
    view.hidden = !operator.hidden
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
      show(intrusion ? 'Someone is here.' : 'Armed.', !state.pred ? 'Waiting for a room prediction.' : 'This space should be empty.', intrusion)
      return
    }
    if (complete) { view.hidden = true; host.inert = false; host.removeAttribute('aria-hidden'); return }
    if (state.pred.present && state.pred.kind === 'person') {
      show('Found you.', state.cam === 'off' ? '0 cameras' : state.cam === 'on' ? 'Camera teaching' : 'Camera stalled')
      if (!hold) hold = setTimeout(() => { complete = true; hold = undefined; render() }, 3000)
      return
    }
    cancelHold()
    show(state.pred.kind === 'object' ? 'An object, not a person.' : 'Nobody is here.', 'Step up to the desk.')
  }
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
  return () => { cancelHold(); unsubscribe?.(); offEvents?.(); visibility.disconnect(); title.dispose(); detail.dispose(); arm.remove(); view.remove(); host.inert = false; host.removeAttribute('aria-hidden') }
}
