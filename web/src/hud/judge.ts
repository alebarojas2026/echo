import { fitProof } from './proof-layout'
import { mountPresenter } from './presenter'
import { boardNow } from './board-time'
import { boardAskClient, makeMockAskClient } from './ask-client'
import { mountPrivacyLine } from './privacy'
import { mountIncidentReport } from './report'
import { publishHealth } from './health-words'
import './health-words.css'
import { sourceWords } from './source-words'
import { loadHudLayout, linkName } from './layout'
import { alignMockState } from './mock-layout'
import { routerWords } from './router-words'
import './judge.css'
import { mountAskRoom } from './ask-room'
import { updateProofVisibility } from './proof-visibility'
import { mountArrival } from './arrival'
import { changingText } from './changing-text'
import { ReadingHold } from './readable-updates'
import type { StateMsg } from '../room/contract'
import type { Feed } from '../room/feed'
import { fetchProof } from '../room/hud-host'
import type { Proof } from './state'
import { presenceTile } from './proof-visibility'
import { judgeMoment } from './judge-moment'
import { hallFirst, hallMoment, walkedThrough } from './judge-hall'
import { mountReplay } from './replay'
import { recordsClient } from './records'
import { holdAdvice } from './dead-zone'

type Panel = { update(state: StateMsg | null, stale: boolean): void; dispose?(): void; reset?(): void }
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
    <header><span>Echo</span><span class="judge-claim">No camera. No microphone.</span><span data-testid="source-badge"></span></header>
    <div class="judge-privacy"></div>
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
  const narrator = field('narrator-text')
  const narratorText = changingText(narrator)
  const hold = new ReadingHold()
  // ?judge=rail keeps the panels' rail on the one spot too: the signal trace, the cards and the proof, for the operator.
  const rail = new URLSearchParams(location.search).get('judge') === 'rail'
  let headlineShape = ''
  let nextNarration = ''
  let clearNarration = false
  const paintNarration = () => {
    const text = hold.update(nextNarration, performance.now(), clearNarration)
    narrator.hidden = !text
    narratorText.set(text)
  }
  const narrationTimer = setInterval(paintNarration, 100)
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
  const disposeProofLayout = fitProof(root)
  const panels = Object.values(extraPanels).map(module => {
    const container = document.createElement('section')
    root.querySelector('.judge-extra')!.append(container)
    return module.mountPanel(container)
  })
  const offPanelEvents = live?.onEvent(event => { if (event.kind === 'reset') panels.forEach(panel => panel.reset?.()) })
  const operator = root.querySelector<HTMLElement>('.hud-operator')!
  operator.hidden = new URLSearchParams(location.search).get('op') !== '1'
  const publishOperator = () => { document.documentElement.dataset.hudOperator = operator.hidden ? 'closed' : 'open' }
  const operatorVisibility = new MutationObserver(publishOperator)
  operatorVisibility.observe(operator, { attributes: true, attributeFilter: ['hidden'] })
  publishOperator()
  Object.values(controlModule)[0]?.mountHudControls(root.querySelector('.operator-controls')!, message => feed?.send(message.cmd, message.args))
  const key = (event: KeyboardEvent) => {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || (event.target as HTMLElement)?.closest('input,select,textarea,[contenteditable]')) return
    if (event.key.toLowerCase() === 'o') operator.hidden = !operator.hidden
    if (event.key === 'Escape') operator.hidden = true
  }
  document.addEventListener('keydown', key)
  const now = () => boardNow(live?.current() ?? null)
  const ask = live?.source === 'ws' ? boardAskClient : makeMockAskClient(now)
  const disposeAsk = mountAskRoom(root.querySelector('header')!, ask, replay ? span => void replay.start(span) : undefined)
  const disposePrivacy = mountPrivacyLine(root.querySelector('.judge-privacy')!)
  const disposeReport = mountIncidentReport(live, recordsClient(live?.source), span => { void replay?.start(span) })
  const disposeArrival = mountArrival(root, live, operator)
  let offReplayClock: (() => void) | undefined
  if (replay) {
    const last = document.createElement('button')
    last.type = 'button'
    last.dataset.testid = 'replay-last'
    last.textContent = 'Replay the last 2 minutes'
    offReplayClock = live?.subscribe(() => { last.disabled = now() === null })
    last.onclick = () => { const end = now(); if (end === null) return; operator.hidden = true; void replay.start({ from_t: end - 120_000, to_t: end }) }
    operator.querySelector('.operator-controls')!.before(last)
  }
  const disposePresenter = mountPresenter(operator, live)
  let disposed = false
  let lastState: StateMsg | null = null
  let lastStale = true
  const walked = walkedThrough(live, () => { if (!disposed) render(lastState, lastStale) })
  const render = (state: StateMsg | null, stale: boolean) => {
    lastState = state
    lastStale = stale
    if (feed?.source === 'mock') state = alignMockState(state)
    state = holdAdvice(state)
    publishHealth(root, state, stale)
    // One spot: the hall is the whole screen, and the state is one headline and one line (judge-hall.ts).
    const hall = hallFirst() && !rail
    document.documentElement.dataset.judgeLayout = hall ? 'hall' : 'rail'
    const [railHeadline, railDetail] = judgeMoment(state, stale)
    const known = !!state && !stale && !state.armed && state.health.status !== 'blind' && !!state.pred && !(state as { replay?: unknown }).replay
    walked.seen(known ? state!.pred!.present && state!.pred!.kind === 'person' : null)
    const { headline, detail, tone } = hall ? hallMoment(state, stale, undefined, walked.active()) : { headline: railHeadline, detail: railDetail, tone: '' }
    field('judge-headline').parentElement!.dataset.tone = tone
    // A replayed second lasts 125 ms at 8x, less than a fade: the headline keeps up by changing at once.
    // A count in the headline ("No movement for 13 s") ticks once a second: only its figures change, so it changes at once too.
    const shape = headline.replace(/\d+/g, '0')
    headlineText.set(headline, !!(state as { replay?: unknown } | null)?.replay || shape === headlineShape)
    headlineShape = shape
    set('judge-detail', detail)
    set('source-badge', sourceWords(state))
    if (!Object.keys(extraPanels).some(path => path.includes('camera'))) set('cam-status', state ? { on: 'Camera on', off: 'Camera unplugged · radio only', stalled: 'Camera stalled · radio only' }[state.cam] ?? 'Camera status unknown' : '')
    nextNarration = !stale ? state?.narration?.text ?? '' : ''
    clearNarration = stale || !state
    paintNarration()
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
  return () => { delete document.documentElement.dataset.judgeLayout; walked.dispose(); operatorVisibility.disconnect(); delete document.documentElement.dataset.hudOperator; offPanelEvents?.(); disposeReport(); disposePrivacy(); disposeProofLayout(); disposePresenter(); offReplayClock?.(); disposeAsk(); disposeArrival(); replay?.dispose(); disposed = true; headlineText.dispose(); narratorText.dispose(); clearInterval(narrationTimer); clearInterval(timer); unsubscribe?.(); document.removeEventListener('keydown', key); panels.forEach(panel => panel.dispose?.()) }
}
import.meta.glob('./judge-layout.css', { eager: true })
import './judge-hall.css'


