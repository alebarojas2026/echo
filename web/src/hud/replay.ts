import type { StateMsg } from '../room/contract'
import type { Feed, FeedSnapshot } from '../room/feed'
import { hudLayout } from './layout'
import { KIND_WORDS, MAX_SPAN_MS, clockTime, secondKind, seconds, type RecordsClient, type Second, type SecondKind, type Span } from './records'
import './replay.css'

// Replay (#537): the screen plays back what the board recorded, one saved second at a time, at 8x, and says so
// the whole time. The 3D room keeps the clock (window events 'room:replay' / 'room:live', answered with
// 'room:replay-frame' and 'room:replay-end'); the panels read the recorded second through the feed returned here.
// Live data keeps arriving underneath, and an intrusion or a tamper hands back to live at once.

export const SPEED = 8
export type ReplayState = StateMsg & { replay?: { t: number; kind: SecondKind } }

/** A recorded second as a state the panels can draw. What the record does not hold stays empty, never guessed. */
export function recordedState(base: StateMsg | null, second: Second): ReplayState {
  const row = second.row
  const kind = secondKind(second)
  const zone = row?.present ? (row.zone ?? 0) : 0
  const seen = kind === 'record' && !!row?.present && zone > 0
  const limit = hudLayout.zones.find((z) => z.id === zone)?.still_alert_s ?? null
  return {
    v: 2, type: 'state', seq: base?.seq ?? 0, cam: base?.cam ?? 'off', router: 'S-home', links: [], model: base?.model ?? null, board: null,
    t: second.t, src: 'replay', replay: { t: second.t, kind },
    health: { status: row?.health ?? 'ok', blind: [], reason: null },
    pred: kind !== 'record' ? null : {
      present: seen, kind: seen ? 'person' : 'none', zone, zone_set: seen ? (row!.zone_set.length ? row!.zone_set : [zone]) : [],
      probs: [], motion: seen ? row!.motion : null, still_s: 0, why: [],
    },
    alert: seen && row!.alert ? { state: 'check_on', zone, still_s: null, limit_s: limit } : { state: 'none', zone: null, still_s: 0, limit_s: null },
    objects: [], xray: null, checkin: null, advice: null, narration: null, teacher: null,
    armed: row?.armed ?? false, tamper: row?.tamper ?? [],
  }
}

export function mountReplay(feed: Feed, records: RecordsClient) {
  const view = document.createElement('section')
  view.className = 'replay'
  view.dataset.testid = 'replay'
  view.setAttribute('aria-label', 'Replay')
  view.hidden = true
  view.innerHTML = `<div class="replay-line"><strong>REPLAY</strong><span>${records.mode === 'mock' ? 'from mock records' : 'from the board’s records'}</span><span data-testid="replay-time"></span><span>${SPEED}x</span></div>
    <div class="replay-track" data-testid="replay-track" role="slider" tabindex="0" aria-label="Replay position"><canvas aria-hidden="true"></canvas><i></i></div>
    <div class="replay-foot"><span data-testid="replay-word" role="status"></span><button type="button" data-testid="replay-live">Back to live</button></div>`
  document.body.append(view)
  const part = <T extends HTMLElement>(selector: string) => view.querySelector<T>(selector)!
  const time = part('[data-testid="replay-time"]')
  const word = part('[data-testid="replay-word"]')
  const track = part('.replay-track')
  const knob = part('.replay-track i')
  const canvas = part<HTMLCanvasElement>('canvas')

  const listeners = new Set<(snap: FeedSnapshot) => void>()
  // Filled by the subscription below, which is called at once with the feed's latest.
  let live: FeedSnapshot = { state: null, receivedAt: null, stale: true, connected: false, source: feed.source }
  let all: Second[] = []
  let at = -1 // the second on screen, or -1 when live
  let ownClock: ReturnType<typeof setInterval> | undefined
  let roomClock: ReturnType<typeof setTimeout> | undefined
  let notice: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  const playing = () => at >= 0
  const snapshot = (): FeedSnapshot => (playing() ? { ...live, stale: false, state: recordedState(live.state, all[at]) } : live)
  const publish = () => { const snap = snapshot(); listeners.forEach((fn) => fn(snap)) }

  const paint = () => {
    const css = getComputedStyle(view)
    const colour = (name: string) => css.getPropertyValue(name).trim()
    const w = (canvas.width = track.clientWidth)
    const h = (canvas.height = 8)
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, w, h)
    // Someone there: the person colour. Recorded and empty: the link grey. Sensor did not know: a thin dim line.
    // No record: nothing at all.
    all.forEach((second, i) => {
      const kind = secondKind(second)
      if (kind === 'none') return
      const x = Math.floor((i / all.length) * w)
      const x1 = Math.max(x + 1, Math.floor(((i + 1) / all.length) * w))
      ctx.fillStyle = kind === 'unknown' ? colour('--edge') : second.row!.present ? colour('--person') : colour('--link')
      if (kind === 'unknown') ctx.fillRect(x, 3, x1 - x, 2)
      else ctx.fillRect(x, 0, x1 - x, h)
    })
  }
  const show = (index: number) => {
    at = index
    const second = all[at]
    const kind = secondKind(second)
    time.textContent = clockTime(second.t)
    word.textContent = kind === 'record' ? '' : KIND_WORDS[kind][0]
    knob.style.transform = `translateX(${((at + 0.5) / all.length) * track.clientWidth}px)`
    track.setAttribute('aria-valuenow', String(at))
    track.setAttribute('aria-valuetext', clockTime(second.t))
    view.dataset.kind = kind
    publish()
  }
  const stopClocks = () => { clearInterval(ownClock); clearTimeout(roomClock); ownClock = roomClock = undefined }
  const finish = (tellRoom: boolean) => {
    request?.abort()
    stopClocks()
    if (!playing()) return
    at = -1
    view.hidden = true
    document.documentElement.dataset.hudReplay = ''
    if (tellRoom) window.dispatchEvent(new CustomEvent('room:live'))
    publish()
  }
  /** Plays from one second on. The room steps through the rows and reports each second it shows. */
  const playFrom = (index: number) => {
    stopClocks()
    show(index)
    const rows = all.slice(index).flatMap((second) => (second.row ? [second.row] : []))
    window.dispatchEvent(new CustomEvent('room:replay', { detail: { rows, speed: SPEED } }))
    // With no 3D room on the page nothing answers, so the same seconds are stepped here.
    roomClock = setTimeout(() => {
      ownClock = setInterval(() => (at + 1 < all.length ? show(at + 1) : finish(false)), 1000 / SPEED)
    }, 600)
  }
  const say = (text: string) => {
    view.hidden = false
    view.dataset.kind = 'notice'
    time.textContent = ''
    word.textContent = text
    clearTimeout(notice)
    notice = setTimeout(() => { if (!playing()) view.hidden = true }, 4000)
  }
  const start = async (span: Span) => {
    finish(true)
    clearTimeout(notice)
    request = new AbortController()
    const from_t = Math.max(span.from_t, span.to_t - MAX_SPAN_MS)
    try {
      const history = await records.history({ from_t, to_t: span.to_t }, request.signal)
      all = seconds(history.rows)
    } catch (reason) {
      if ((reason as Error)?.name !== 'AbortError') say('The records could not be read.')
      return
    }
    if (!all.length) return say('No record for this time.')
    view.hidden = false
    document.documentElement.dataset.hudReplay = 'on'
    track.setAttribute('aria-valuemin', '0')
    track.setAttribute('aria-valuemax', String(all.length - 1))
    paint()
    playFrom(0)
  }

  const onFrame = (event: Event) => {
    if (!playing()) return
    stopClocks()
    const index = Math.round(((event as CustomEvent<{ t: number }>).detail.t - all[0].t) / 1000)
    if (index >= 0 && index < all.length) show(index)
  }
  const onEnd = () => finish(false)
  const onKey = (event: KeyboardEvent) => {
    if (!playing()) return
    if (event.key === 'Escape') finish(true)
    if (event.target === track && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) playFrom(Math.min(all.length - 1, Math.max(0, at + (event.key === 'ArrowLeft' ? -5 : 5))))
  }
  track.onpointerdown = (event) => {
    if (!playing()) return
    const box = track.getBoundingClientRect()
    playFrom(Math.min(all.length - 1, Math.max(0, Math.floor(((event.clientX - box.left) / box.width) * all.length))))
  }
  part('[data-testid="replay-live"]').onclick = () => finish(true)
  window.addEventListener('room:replay-frame', onFrame)
  window.addEventListener('room:replay-end', onEnd)
  document.addEventListener('keydown', onKey)
  const offState = feed.subscribe((snap) => {
    const tampered = !live.state?.tamper?.length && !!snap.state?.tamper?.length
    live = snap
    if (playing() && tampered) finish(true)
    if (!playing()) publish()
  })
  // What is happening now comes before what happened then.
  const offEvents = feed.onEvent((event) => { if (event.kind === 'intrusion' || event.kind === 'tamper') finish(true) })

  const shown: Feed = {
    source: feed.source,
    current: snapshot,
    subscribe(fn) { listeners.add(fn); fn(snapshot()); return () => listeners.delete(fn) },
    onEvent: (fn) => feed.onEvent(fn),
    send: (cmd, args) => feed.send(cmd, args),
  }
  return {
    /** The feed the panels read: the recorded second while replaying, the live feed otherwise. */
    feed: shown,
    start,
    stop: () => finish(true),
    dispose() {
      finish(true)
      clearTimeout(notice)
      offState()
      offEvents()
      window.removeEventListener('room:replay-frame', onFrame)
      window.removeEventListener('room:replay-end', onEnd)
      document.removeEventListener('keydown', onKey)
      view.remove()
    },
  }
}
