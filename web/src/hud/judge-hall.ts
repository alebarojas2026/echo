import type { StateMsg } from '../room/contract'
import { motionWord, shownAlert } from '../room/shown-alert'
import { judgeMoment } from './judge-moment'
import { hudLayout, type HudLayout } from './layout'

// The hall-first judge's page (the one-spot layout): the hall is the whole screen, and the state is said once, as
// one headline and one line under it. What the cards in the rail said (the still count, the alert, the check-in)
// is said here instead.

export type Tone = '' | 'fault' | 'action'
export interface Moment { headline: string; detail: string; tone: Tone }

/** The line under the alert's headline: how to answer it. */
export const CHECKIN_WORDS = 'Step aside and back to say you’re okay.'
/** A check-in is shown this long, as the stillness card showed it. */
const CHECKIN_SHOWN_MS = 6000

/** The layout the hall-first page is for: one spot (the same test the spot's own headline uses). */
export function hallFirst(layout: HudLayout = hudLayout): boolean {
  return layout.zones.length === 1
}

const seconds = (value: number | null | undefined) => value == null ? '__' : String(Math.floor(value))

export function hallMoment(state: StateMsg | null, stale: boolean, layout: HudLayout = hudLayout): Moment {
  const [headline, detail] = judgeMoment(state, stale, layout)
  const said = (tone: Tone = ''): Moment => ({ headline, detail, tone })
  if (!state || stale || (state as { replay?: unknown }).replay) return said()
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
  if (headline === 'Nobody is here') return { headline: 'Nobody is here.', detail: 'Step up to the desk.', tone: '' }
  return said()
}
