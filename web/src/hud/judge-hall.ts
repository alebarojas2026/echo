import type { StateMsg } from '../room/contract'
import { motionWord, shownAlert } from '../room/shown-alert'
import { judgeMoment } from './judge-moment'
import { hudLayout, type HudLayout } from './layout'
import { SHORT_VISIT_MS } from '../room/motion'

// The hall-first judge's page (the one-spot layout): the hall is the whole screen, and the state is said once, as
// one headline and one line under it. What the cards in the rail said (the still count, the alert, the check-in)
// is said here instead.

export type Tone = '' | 'fault' | 'action'
export interface Moment { headline: string; detail: string; tone: Tone }

/** The line under the alert's headline: how to answer it. */
export const CHECKIN_WORDS = "Step aside and back to say you're okay."
/** A check-in is shown this long, as the stillness card showed it. */
const CHECKIN_SHOWN_MS = 6000

/** A walk straight through the one spot (the board's passed_by event) is said this long; then the page is back
 *  to "Nobody is here." */
export const WALKED_MS = 3000
/** What is said for it: calm, no fault colour. It is not an alert. Never a side, never a count. */
export const WALKED: Moment = { headline: 'Someone walked through.', detail: 'Nobody stopped.', tone: '' }

/**
 * Keeps whether a walk-through is being said. `active()` is true for WALKED_MS after either of the two ways the
 * board records one on the one-spot layout: a passed_by event (a quick crossing), or an enter event followed by
 * its exit event within SHORT_VISIT_MS (a slow one). Only the board's events start it, never a state alone, so
 * the sealed record always has what the screen said. A reset ends it. `changed` is called when it starts and
 * when it ends.
 */
export function walkedThrough(feed: { onEvent(fn: (event: { kind: string; t?: number }) => void): () => void } | null | undefined, changed: () => void, now: () => number = () => performance.now(), oneSpot: () => boolean = hallFirst) {
  let until = -Infinity
  let timer: ReturnType<typeof setTimeout> | undefined
  /** The board's time of the last enter event that has had no exit yet. */
  let entered: number | null = null
  const start = () => {
    until = now() + WALKED_MS
    clearTimeout(timer)
    timer = setTimeout(changed, WALKED_MS + 20)
    changed()
  }
  const off = feed?.onEvent((event) => {
    if (!oneSpot()) return
    const t = typeof event.t === 'number' && Number.isFinite(event.t) ? event.t : null
    if (event.kind === 'passed_by') start()
    else if (event.kind === 'enter') entered = t
    else if (event.kind === 'exit') {
      // The board's own times: a visit this short was a walk through. A clock that ran backwards is no visit.
      const short = entered !== null && t !== null && t >= entered && t - entered <= SHORT_VISIT_MS
      entered = null
      if (short) start()
    } else if (event.kind === 'reset') {
      entered = null
      if (until > -Infinity) {
        until = -Infinity
        clearTimeout(timer)
        changed()
      }
    }
  })
  return { active: () => now() < until, dispose: () => { clearTimeout(timer); off?.() } }
}

/** "Nobody is here.", as the page says it. */
export const NOBODY: Moment = { headline: 'Nobody is here.', detail: 'Step up to the desk.', tone: '' }

/**
 * On the one spot "Someone is here." is said the moment the board says so, and the line under it waits: for the
 * first SHORT_VISIT_MS of a presence it is empty, so a walk through never flashes "Standing still" on its way to
 * "Someone walked through.". From then on it is the still or moving line with the board's count, which runs from
 * the true arrival. `presentMs`: how long a person has been here by the board's clock (null: nobody, or nothing
 * to go by). An armed space, an alert and a check-in say what they always said.
 */
export function earlyMoment(moment: Moment, presentMs: number | null): Moment | null {
  if (moment.headline !== 'Someone is here.' || moment.tone !== '' || presentMs === null || presentMs >= SHORT_VISIT_MS) return null
  return { ...moment, detail: '' }
}

/** The layout the hall-first page is for: one spot (the same test the spot's own headline uses). */
export function hallFirst(layout: HudLayout = hudLayout): boolean {
  return layout.zones.length === 1
}

const seconds = (value: number | null | undefined) => value == null ? '__' : String(Math.floor(value))

export function hallMoment(state: StateMsg | null, stale: boolean, layout: HudLayout = hudLayout, walked = false): Moment {
  const [headline, detail] = judgeMoment(state, stale, layout)
  const said = (tone: Tone = ''): Moment => ({ headline, detail, tone })
  // A replayed second with nothing to show keeps its own words; one with a record reads as it did live.
  const replayed = (state as { replay?: { kind?: string } } | null)?.replay?.kind
  if (!state || stale || (replayed && replayed !== 'record')) return said()
  if (state.armed && state.tamper?.length) return said('fault')
  if (state.health.status === 'blind' || !state.pred || state.router !== 'S-home') return said()
  const line = layout.presence?.line
  const alert = shownAlert(state, line)
  const here = state.pred.present && state.pred.kind === 'person'
  if (here && alert?.state === 'check_on') return { headline: `No movement for ${seconds(alert.still_s)} s`, detail: CHECKIN_WORDS, tone: 'fault' }
  const age = state.checkin ? state.t - state.checkin.t : Infinity
  // The line under it is the spot's own headline, as it would stand alone ("Someone is here, moving").
  if (age >= 0 && age <= CHECKIN_SHOWN_MS) return { headline: 'Check-in received', detail: here || state.pred.kind === 'object' ? headline : '', tone: 'action' }
  if (here) {
    const motion = motionWord(state, line)
    // No "for 0 s": the count is said from its first whole second (it is the board's, from the true arrival).
    const counted = alert?.state === 'counting' && motion !== 'moving' && (alert.still_s ?? 0) >= 1 ? ` for ${seconds(alert.still_s)} s` : ''
    return { headline: 'Someone is here.', detail: motion === 'moving' ? 'Moving' : motion === 'still' ? `Standing still${counted}` : '', tone: state.armed ? 'fault' : '' }
  }
  // Somebody walked straight through a moment ago (walkedThrough): said only while nobody is here and the space
  // is not armed. Armed, the walk-up card says it its own way.
  if (headline === 'Nobody is here') return walked && !state.armed ? WALKED : NOBODY
  return said()
}
