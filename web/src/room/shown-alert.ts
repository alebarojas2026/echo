import type { Alert, StateMsg } from './contract'
import { PRESENCE_LINE } from './frame'

const NONE: Alert = { state: 'none', zone: null, still_s: 0, limit_s: null }

/**
 * The no-movement alert as the screen shows it: the board's alert block, except on a layout with a presence line
 * once the same state says nobody is on the spot. The board lets go of an alert a moment after the person has
 * left; the headline, the alert card, the floor's colour and its "No movement" are one decision here, so an empty
 * spot never carries an alert. (A hidden decision, pred null, changes nothing: blind is said in its own words.)
 */
export function shownAlert(state: Pick<StateMsg, 'alert' | 'pred'> | null, line: string | null | undefined = PRESENCE_LINE): Alert | null {
  if (!state) return null
  return line && state.pred && !state.pred.present ? NONE : state.alert
}

/** moving | still for the person on the spot, said one way everywhere: while the no-movement alert is up the
 *  word is "still", whatever a single decision says, so "moving" never stands over "No movement". */
export function motionWord(state: Pick<StateMsg, 'alert' | 'pred'>, line: string | null | undefined = PRESENCE_LINE): string | null {
  if (!state.pred?.present) return null
  return shownAlert(state, line)?.state === 'check_on' ? 'still' : state.pred.motion ?? null
}
