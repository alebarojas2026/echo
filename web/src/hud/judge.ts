import { loadHudLayout, linkName } from './layout'
import { alignMockState } from './mock-layout'
import { routerWords } from './router-words'
import './judge.css'
import { mountAskRoom } from './ask-room'
import { updateProofVisibility } from './proof-visibility'
import { mountArrival } from './arrival'
import { changingText } from './changing-text'
import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { fetchProof } from '../room/hud-host'
import type { Proof } from './state'
import { presenceTile } from './proof-visibility'
import { judgeMoment } from './judge-moment'
import { mountReplay } from './replay'
import { recordsClient } from './records'

type Panel = { update(state: StateMsg | null, stale: boolean): void; dispose?(): void }
type PanelModule = { mountPanel(root: HTMLElement): Panel }
const extraPanels = import.meta.glob<PanelModule>('./judge-*-panel.ts', { eager: true })
const controlModule = import.meta.glob<{ mountHudControls(root: HTMLElement, send: (message: { cmd: Parameters<Feed['send']>[0]; args: Record<string, string | boolean> }) => void): void }>('./controls.ts', { eager: true })

export function mountHud(root: HTMLElement, feed: Feed | null) {
  // The panels read the feed through the replay: live as it comes, or a recorded second while one plays.
  const replay = feed ? mountReplay(feed, recordsClient(feed.source)) : null
  const live = feed
  feed = replay?.feed ?? feed
  root.classList.add('judge')
  root.innerHTML = `
    <header><span>Radio Sight</span><span data-testid="source-badge"></span></header>
    <section class="judge-moment" aria-live="polite"><h1 data-testid="judge-headline"></h1><p data-testid="judge-detail"></p></section>
    <div class="judge-extra"></div>
    ${Object.keys(extraPanels).some(path => path.includes("camera")) ? "" : '<p data-testid="cam-status"></p>'}
    <p class="judge-narrator" data-testid="narrator-text"></p>
    <footer><dl></dl></footer>
    <aside class="hud-operator" hidden aria-label="Operator controls"><h2>Operator controls</h2><div class="operator-controls"></div><dl class="debug"></dl></aside>
  `
  const field = (id: string) => root.querySelector<HTMLElement>(`[data-testid="${id}"]`)!
  const set = (id: string, text: string) => { field(id).textContent = text }
  const headlineText = changingText(field('judge-headline'))
  const debug = root.querySelector('.debug')!
  for (const id of ['pred-zone', 'pred-zone-set', 'pred-kind', 'pred-motion', 'why-links', 'router-spot', 'narrator-source', 'no-data', 'sensor-blind', 'health-links']) {
    const value = document.createElement('dd')
    value.dataset.testid = id
    debug.append(value)
  }
  const proofLabels = { 'presence-score': 'Presence', 'zone-score': 'Zone agreement', 'person-object-score': 'Person / object', 'train-seconds': 'Train time', 'ms-per-decision': 'Per decision', watts: 'Watts', 'bytes-out': 'Bytes out', 'images-stored': 'Images stored', 'models-count': 'Models' }
  const metrics = root.querySelector('footer dl')!
  for (const [id, label] of Object.entries(proofLabels)) {
    const item = document.createElement('div')
    item.innerHTML = `<dt>${label}</dt><dd data-testid="${id}">__</dd>`
    // The presence score never stands alone (#656): what always saying "nobody" would score sits under it.
    if (id === 'presence-score') { item.className = 'proof-wide'; item.insertAdjacentHTML('beforeend', '<dd class="proof-note" data-testid="presence-baseline" hidden></dd>') }
    metrics.append(item)
  }
  updateProofVisibility(root)
  const panels = Object.values(extraPanels).map(module => {
    const container = document.createElement('section')
    root.querySelector('.judge-extra')!.append(container)
    return module.mountPanel(container)
  })
  const operator = root.querySelector<HTMLElement>('.hud-operator')!
  operator.hidden = new URLSearchParams(location.search).get('op') !== '1'
  Object.values(controlModule)[0]?.mountHudControls(root.querySelector('.operator-controls')!, message => feed?.send(message.cmd, message.args))
  const key = (event: KeyboardEvent) => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || (event.target as HTMLElement)?.closest('input,select,textarea,[contenteditable]')) return
    if (event.key.toLowerCase() === 'o') operator.hidden = !operator.hidden
    if (event.key === 'Escape') operator.hidden = true
  }
  document.addEventListener('keydown', key)
  const disposeAsk = mountAskRoom(root.querySelector('header')!, undefined, replay ? span => void replay.start(span) : undefined)
  const disposeArrival = mountArrival(root, live, operator)
  if (replay) {
    const last = document.createElement('button')
    last.type = 'button'
    last.dataset.testid = 'replay-last'
    last.textContent = 'Replay the last 2 minutes'
    last.onclick = () => { operator.hidden = true; void replay.start({ from_t: Date.now() - 120_000, to_t: Date.now() }) }
    operator.querySelector('.operator-controls')!.before(last)
  }
  let disposed = false
  let lastState: StateMsg | null = null
  let lastStale = true
  const render = (state: StateMsg | null, stale: boolean) => {
    lastState = state
    lastStale = stale
    if (feed?.source === 'mock') state = alignMockState(state)
    const [headline, detail] = judgeMoment(state, stale)
    headlineText.set(headline)
    set('judge-detail', detail)
    set('source-badge', state?.src === 'sim' ? 'SIM' : state?.src === 'replay' ? 'REPLAY' : state?.links.some(link => (link.rate_hz ?? 0) > 0) ? 'LIVE' : 'NO RADIO')
    if (!Object.keys(extraPanels).some(path => path.includes('camera'))) set('cam-status', state ? { on: 'Camera on', off: 'Camera unplugged · radio only', stalled: 'Camera stalled · radio only' }[state.cam] : '')
    set('narrator-text', !stale ? state?.narration?.text ?? '' : '')
    field('narrator-text').hidden = !field('narrator-text').textContent
    set('pred-zone', state?.pred?.zone ? String(state.pred.zone) : '__')
    set('pred-zone-set', state?.pred?.zone_set.join(' or ') ?? '__')
    set('pred-kind', state?.pred?.kind ?? '__')
    set('pred-motion', state?.pred?.motion ?? '__')
    set('why-links', state?.pred?.why.map(id => linkName(id)).join('; ') ?? '')
    field('why-links').dataset.links = state?.pred?.why.join(',') ?? ''
    set('health-links', state?.health.status === 'degraded' ? state.links.filter(link => link.status !== 'ok').map(link => linkName(link.id)).join('; ') : '')
    set('router-spot', state ? routerWords(state.router) : '')
    set('narrator-source', state?.narration?.source ?? '')
    set('no-data', stale || !state ? 'No data' : '')
    set('sensor-blind', !stale && state?.health.status === 'blind' ? 'Sensor blind' : '')
    panels.forEach(panel => panel.update(state, stale))
  }
  void loadHudLayout().then(() => { if (!disposed) render(lastState, lastStale) })
  render(null, true)
  const unsubscribe = feed?.subscribe(({ state, stale }) => render(state, stale))
  const number = (value: number | null | undefined, suffix = '') => Number.isFinite(value) ? `${value}${suffix}` : '__'
  const score = (value: { correct: number | null; total: number | null } | null | undefined) => value?.correct != null && value.total ? number(Math.round(100 * value.correct / value.total), '%') : '__'
  const refresh = async () => {
    const proof = await fetchProof() as Proof | null
    if (disposed) return
    const presence = presenceTile(proof?.presence)
    const values = [presence.score, score(proof?.zone), score(proof?.person_vs_object), number(proof?.train_s, ' s'), number(proof?.ms_per_decision?.p50, ' ms'), number(proof?.watts?.radio_only), number(proof?.bytes_out), number(proof?.images_stored), number(proof?.models_on_board)]
    Object.keys(proofLabels).forEach((id, index) => set(id, values[index]))
    set('presence-baseline', presence.baseline)
    field('presence-baseline').hidden = !presence.baseline
    updateProofVisibility(root)
  }
  void refresh()
  const timer = setInterval(refresh, 30000)
  return () => { disposeAsk(); disposeArrival(); replay?.dispose(); disposed = true; headlineText.dispose(); clearInterval(timer); unsubscribe?.(); document.removeEventListener('keydown', key); panels.forEach(panel => panel.dispose?.()) }
}
import.meta.glob('./judge-layout.css', { eager: true })


