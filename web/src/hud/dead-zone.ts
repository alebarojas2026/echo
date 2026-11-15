import type { Advice, StateMsg } from '../room/contract'
import { HOME_SPOT, LINK_IDS, NODES, STRIP_M, parseLinkId, routerId } from '../room/frame'

// Dead zones on the screen (#612): one link, one place. The router's Wi-Fi link to the board is read out all the
// time; when the board gives advice (it only does while that link is dropping 3 dB or more, CONTRACTS.md section 6)
// the screen says a dead zone was found and where to move the router, and after the move it shows the gain the
// board measured. Every number here is one the board sent: nothing is worked out from anything else.

/** The contract's line for "dropping": the board gives advice from this drop on. */
export const WEAK_DB = 3

export const dbm = (value: number | null | undefined) =>
  value == null || !Number.isFinite(value) ? '__' : `${value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)} dBm`

/** The router's Wi-Fi link to the receiver, from the layout: the link advice is about. */
export function wifiLinkId(advice?: Advice | null): string | null {
  if (advice?.link) return advice.link
  const router = routerId()
  const wifi = LINK_IDS.filter((id) => parseLinkId(id)?.kind === 'wifi')
  return wifi.find((id) => parseLinkId(id)?.tx === router) ?? wifi[0] ?? null
}

/** "Pi A to Board": the two ends of a link by their names in nodes.json. */
export function linkEnds(id: string | null): string {
  const parts = id ? parseLinkId(id) : null
  if (!parts) return 'the router to the board'
  const name = (node: string) => NODES[node]?.name || (node === routerId() ? 'the router' : 'the board')
  return `${name(parts.tx)} to ${name(parts.rx)}`
}

export type WifiStatus = 'strong' | 'weak' | 'no-signal' | 'no-baseline' | 'no-data'
export interface WifiLine { status: WifiStatus; word: string; value: string; ends: string }

/** The calm Wi-Fi line: a word and the link's drop from its baseline, as the board sent it. */
export function wifiLine(state: StateMsg | null, stale: boolean): WifiLine {
  const id = wifiLinkId(state?.advice)
  const ends = linkEnds(id)
  if (!state || stale) return { status: 'no-data', word: 'no data', value: '', ends }
  const link = state.links.find((row) => row.id === id)
  if (!link || link.status !== 'ok' || link.dbm == null) return { status: 'no-signal', word: 'no signal', value: '', ends }
  if (link.drop_db == null) return { status: 'no-baseline', word: 'no baseline yet', value: dbm(link.dbm), ends }
  const change = -link.drop_db
  const text = Math.abs(change).toFixed(1)
  const value = `${text === '0.0' ? '' : change < 0 ? '−' : '+'}${text} dB`
  return link.drop_db >= WEAK_DB ? { status: 'weak', word: 'weak', value, ends } : { status: 'strong', word: 'strong', value, ends }
}

/** "30 cm left": how far and which way, from advice.move_m. On the desk the sides are named as seen on the screen
 *  (x runs east along the desk, so west is left); on the square they are compass points. */
export function moveWords(advice: Pick<Advice, 'move_m'>, desk = !!STRIP_M): string {
  const [dx, dy] = advice.move_m ?? [0, 0]
  const cm = Math.round(Math.hypot(dx, dy) * 100)
  if (!Number.isFinite(cm) || cm === 0) return ''
  const alongX = Math.abs(dx) >= Math.abs(dy)
  const way = alongX ? (desk ? (dx < 0 ? 'left' : 'right') : dx < 0 ? 'west' : 'east') : dy < 0 ? 'south' : 'north'
  return `${cm} cm ${way}`
}

export type DeadZoneStep = 'found' | 'measuring' | 'better' | 'worse'
export interface DeadZone {
  step: DeadZoneStep
  headline: string
  detail: string
  /** The card's large line: what to do, then "Measuring…", then the gain the board measured. */
  text: string
  /** Which way the advice points along the desk: -1 left or west, 1 right or east, 0 otherwise. */
  way: -1 | 0 | 1
  before: number | null
  after: number | null
}

/** The board's last advice, kept while the router stays on the spot it advised: a feed that drops the advice
 *  once the link is clear (the room's mock does) still shows "measuring" instead of a paused screen. */
let kept: Advice | null = null
export function holdAdvice<T extends StateMsg | null>(state: T): T {
  if (!state) return state
  if (state.advice) kept = state.advice
  else if (state.router === HOME_SPOT || state.router !== kept?.to_spot) kept = null
  return kept && !state.advice ? { ...state, advice: kept } : state
}

export function deadZone(state: StateMsg | null, stale: boolean): DeadZone | null {
  const advice = !stale ? state?.advice : null
  if (!state || !advice) return null
  const where = moveWords(advice)
  const [dx, dy] = advice.move_m ?? [0, 0]
  const way = Math.abs(dx) >= Math.abs(dy) && dx !== 0 ? (dx < 0 ? -1 : 1) : 0
  const base = { way, before: advice.before_dbm, after: advice.after_dbm } as const
  if (state.router !== advice.to_spot) {
    return {
      ...base, step: 'found', after: null, headline: 'Dead zone found',
      detail: `Something is blocking the Wi-Fi from ${linkEnds(wifiLinkId(advice))}`,
      text: where ? `Move the router ${where}` : advice.text,
    }
  }
  const moved = where ? `Router moved ${where}` : 'Router moved'
  if (advice.before_dbm == null || advice.after_dbm == null) {
    return { ...base, step: 'measuring', headline: 'Router moved', detail: 'Measuring the Wi-Fi at the new spot', text: 'Measuring…' }
  }
  // The gain is said to one decimal, so it is judged at one decimal too: 0.0 is no change, never "stronger".
  const gain = Math.round((advice.after_dbm - advice.before_dbm) * 10) / 10
  const size = `${Math.abs(gain).toFixed(1)} dB`
  return gain > 0
    ? { ...base, step: 'better', headline: 'Dead zone fixed', detail: moved, text: `+${size} stronger` }
    : { ...base, step: 'worse', headline: 'No gain at this spot', detail: moved, text: gain < 0 ? `−${size} weaker` : 'No change' }
}
