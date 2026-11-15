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

/** One reading without the person inside a visit is a dropped reading, not a leaving (the walk-up card's rule). */
const DROPPED_MS = 300

/**
 * Keeps whether a walk-through is being said. `active()` is true for WALKED_MS after either of the two ways the
 * board says it on the one-spot layout: a passed_by event (a quick crossing), or an arrival whose leaving comes
 * within SHORT_VISIT_MS (a slow one: enter, then exit). A reset ends it. `changed` is called when an event starts
 * it and when it ends; `seen` is called from the page's own drawing, which reads `active()` straight after.
 */
export function walkedThrough(feed: { onEvent(fn: (event: { kind: string }) => void): () => void } | null | undefined, changed: () => void, now: () => number = () => performance.now(), oneSpot: () => boolean = hallFirst) {
  let until = -Infinity
  let timer: ReturnType<typeof setTimeout> | undefined
  /** Since when someone has been here; and the short visit that has just ended, in case it has not. */
  let since: number | null = null
  let ended: { since: number; at: number } | null = null
  const start = () => {
    until = now() + WALKED_MS
    clearTimeout(timer)
    timer = setTimeout(changed, WALKED_MS + 20)
  }
  const off = feed?.onEvent((event) => {
    if (event.kind === 'passed_by' && oneSpot()) {
      start()
      changed()
    } else if (event.kind === 'reset' && until > -Infinity) {
      until = -Infinity
      clearTimeout(timer)
      changed()
    }
  })
  return {
    active: () => now() < until,
    /** What the board says now: someone is here (true), nobody is (false), or nothing to go by (null: no data,
     *  a blind sensor, an armed space, a replayed second). */
    seen(here: boolean | null) {
      if (!oneSpot()) return
      const t = now()
      if (here === null) {
        since = null
        ended = null
      } else if (here) {
        if (since === null) {
          if (ended && t - ended.at <= DROPPED_MS) {
            // They had not left: the visit carries on, and nothing was walked through.
            since = ended.since
            until = -Infinity
            clearTimeout(timer)
          } else since = t
        }
        ended = null
      } else if (since !== null) {
        if (t - since <= SHORT_VISIT_MS) {
          ended = { since, at: t }
          start()
        }
        since = null
      }
    },
    dispose: () => { clearTimeout(timer); off?.() },
  }
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
    const counted = alert?.state === 'counting' && motion !== 'moving' ? ` for ${seconds(alert.still_s)} s` : ''
    return { headline: 'Someone is here.', detail: motion === 'moving' ? 'Moving' : motion === 'still' ? `Standing still${counted}` : '', tone: state.armed ? 'fault' : '' }
  }
  // Somebody walked straight through a moment ago (walkedThrough): said only while nobody is here and the space
  // is not armed. Armed, the walk-up card says it its own way.
  if (headline === 'Nobody is here') return walked && !state.armed ? WALKED : { headline: 'Nobody is here.', detail: 'Step up to the desk.', tone: '' }
  return said()
}
