import type { Feed } from '../room/feed'
import type { CmdName } from '../room/contract'
import { boardNow } from './board-time'
import './presenter.css'

export function mountPresenter(operator: HTMLElement, feed: Feed | null) {
  const section = document.createElement('section')
  section.className = 'presenter'; section.dataset.testid = 'presenter'
  section.innerHTML = `<h2>Present the demo</h2><p>R Reset · M Move router · H Router home · T Lesson · B Same-place baseline</p>
    <div class="presenter-actions"><button data-action="lesson">Start lesson</button><button data-action="stop">Stop lesson</button><button data-action="same">Baseline: same place</button><button data-action="new">Baseline: new place</button><button data-action="reset">Reset between visitors</button><button data-action="move">Router moved to advice</button><button data-action="home">Router home</button></div>
    <p role="status" data-testid="presenter-status">Commands go to the connected board.</p>
    <div class="presenter-clock"><h3>Board clock</h3><p data-testid="clock-status"></p><button data-action="read-clock">Read board clock</button><button data-action="set-clock">Set from this computer</button><p>A clock step briefly restarts sensing. Disarm and stop the lesson first.</p></div>`
  operator.querySelector('h2')!.after(section)
  const actions = section.querySelector('.presenter-actions')!
  const arm = operator.querySelector<HTMLButtonElement>('[data-testid="arm-button"]')
  if (arm) actions.prepend(arm)
  const replay = operator.querySelector('[data-testid="replay-last"]')
  if (replay) actions.append(replay)
  const advanced = operator.querySelector('.operator-controls')
  if (advanced) { const details = document.createElement('details'); details.innerHTML = '<summary>Advanced recording controls</summary>'; advanced.before(details); details.append(advanced) }
  const button = (name: string) => section.querySelector<HTMLButtonElement>(`[data-action="${name}"]`)!
  const status = section.querySelector<HTMLElement>('[role="status"]')!
  const clockStatus = section.querySelector<HTMLElement>('[data-testid="clock-status"]')!
  let pendingSession: string | null = null, recording = false, disposed = false
  const current = () => feed?.current()
  const ready = () => !!current()?.state && !current()?.stale && !!current()?.connected
  const send = (cmd: string, args: Record<string, unknown> = {}, words = 'Command requested') => {
    if (operator.hidden || !ready()) return
    feed?.send(cmd as CmdName, args); status.textContent = words
  }
  const paint = () => {
    const state = current()?.state
    const lesson = !!(state?.model?.training as {lesson?:unknown}|null)?.lesson
    for (const name of ['lesson','stop','same','new','reset','move','home']) button(name).disabled = !ready()
    button('lesson').disabled ||= state?.cam !== 'on' || lesson || recording || !!pendingSession
    button('stop').disabled ||= !lesson && !recording && !pendingSession
    button('move').disabled ||= !state?.advice?.to_spot
  }
  button('lesson').onclick = () => {
    const t = boardNow(current() ?? null)
    if (!ready() || t === null || button('lesson').disabled) return
    pendingSession = `lesson-${t}-${crypto.randomUUID().slice(0,8)}`
    send('record_start', { session: pendingSession, purpose: 'train', walker: 'presenter' }, 'Starting the lesson recording…')
    paint()
  }
  button('stop').onclick = () => { pendingSession = null; send('record_stop', {}, 'Lesson stop requested'); recording = false; paint() }
  button('same').onclick = () => send('baseline', {keep_model:true}, 'Same-place baseline requested; keep the space empty')
  button('new').onclick = () => { if (confirm('Start a new-place baseline and forget the current model?')) send('baseline', {}, 'New-place baseline requested; keep the space empty') }
  button('reset').onclick = () => send('reset', {}, 'Reset requested')
  button('move').onclick = () => { const spot = current()?.state?.advice?.to_spot; if (spot) send('router_moved', {spot}, 'Router move requested') }
  button('home').onclick = () => send('router_home', {}, 'Router home requested')
  const offState = feed?.subscribe(paint)
  const offEvent = feed?.onEvent(event => {
    if (event.kind === 'recording') {
      recording = event.info.on === true
      if (pendingSession && recording && event.info.session === pendingSession) { pendingSession = null; feed?.send('train'); status.textContent = 'Lesson requested; watching for board progress' }
    }
    if (event.kind === 'reset') { pendingSession = null; recording = false }
    paint()
  })
  const key = (event: KeyboardEvent) => {
    if (operator.hidden || event.repeat || event.ctrlKey || event.altKey || event.metaKey || (event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable]')) return
    const action = ({r:'reset',m:'move',h:'home',t:'lesson',b:'same'} as Record<string,string>)[event.key.toLowerCase()]
    if (!action) return
    event.preventDefault(); event.stopImmediatePropagation(); button(action).click()
  }
  window.addEventListener('keydown', key, true)
  const realClock = feed?.source === 'ws' || new URLSearchParams(location.search).get('clock') === 'board'
  let clockReady = false, busy = false, request: AbortController | null = null
  const clock = async (set = false) => {
    if (operator.hidden || !realClock || busy || (set && !clockReady)) return
    busy = true; button('read-clock').disabled = true; button('set-clock').disabled = true
    request = new AbortController(); const timeout = setTimeout(() => request?.abort(), 5000)
    try {
      const response = await fetch('/clock', { method:set?'POST':'GET', cache:'no-store', signal:request.signal, ...(set ? {headers:{'content-type':'application/json'},body:JSON.stringify({t:Date.now()})} : {}) })
      const value = await response.json()
      if (!response.ok || (set && !value.ok)) throw new Error(value.why || 'The board clock could not be read')
      if (!set && !Number.isFinite(value.t)) throw new Error('The board clock response has no time')
      clockReady = !set && !value.busy
      clockStatus.textContent = set ? (value.stepping ? 'Clock step requested. Sensing will reconnect.' : 'Board clock is already set.') : value.busy || `Board clock differs by ${Math.round((Date.now()-value.t)/1000)} s`
    } catch (error) { clockReady = false; clockStatus.textContent = error instanceof Error ? error.message : 'The board clock did not answer' }
    finally { clearTimeout(timeout); request = null; busy = false; if (!disposed) { button('read-clock').disabled = !realClock; button('set-clock').disabled = !clockReady } }
  }
  button('read-clock').onclick = () => void clock()
  button('set-clock').onclick = () => void clock(true)
  button('set-clock').disabled = true; button('read-clock').disabled = !realClock
  clockStatus.textContent = realClock ? 'Read the board clock before setting it.' : 'The mock has no board clock.'
  const visibility = new MutationObserver(() => { if (!operator.hidden) void clock() })
  visibility.observe(operator, {attributes:true,attributeFilter:['hidden']})
  if (!operator.hidden) void clock()
  return () => { disposed = true; request?.abort(); visibility.disconnect(); offState?.(); offEvent?.(); window.removeEventListener('keydown',key,true); section.remove() }
}
