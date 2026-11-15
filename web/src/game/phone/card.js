// What the caregiver's phone shows for a brain state. No DOM in here, so it can be tested with node.
// Message shapes come from CONTRACTS.md v2, section 5. Every number shown comes from the state.

import { ZONES } from '../zones.js'

export { ZONES }
export const STALE_MS = 1000 // section 6: NO DATA when the last state is older than 1 s

export function isState(msg) {
  return Boolean(msg) && msg.v === 2 && msg.type === 'state'
}

function zoneName(z) {
  return ZONES[z] ? `the ${ZONES[z]} zone` : 'the room'
}

// card(state, age of that state in ms) -> { mode, label, title, detail, zone, checkinT }
// mode: 'intrusion' | 'alert' | 'armed' | 'calm' | 'waiting' | 'blind' | 'nodata'. label is the word that goes with the colour.
export function card(state, ageMs) {
  const checkinT = state?.checkin?.t ?? null
  if (!isState(state) || ageMs > STALE_MS) {
    return { mode: 'nodata', label: 'NO DATA', title: 'No data from the board.', detail: 'Waiting for the radio feed.', zone: null, checkinT: null }
  }
  if (state.health?.status === 'blind') {
    return { mode: 'blind', label: 'SENSOR BLIND', title: 'The radio cannot read the room right now.', detail: 'This does not mean the room is empty.', zone: null, checkinT }
  }
  // Armed (section 6): this space should be empty. A person in it is an intrusion; with no prediction
  // the card never says "all clear".
  if (state.armed === true) {
    const pred = state.pred
    if (!pred) return { mode: 'waiting', label: 'ARMED', title: 'The radio is not ready yet.', detail: 'It cannot say the space is empty.', zone: null, checkinT }
    if (pred.present && pred.kind === 'person') {
      return { mode: 'intrusion', label: 'INTRUSION', title: `Someone is in ${zoneName(pred.zone)}.`, detail: 'This space should be empty.', zone: ZONES[pred.zone] ?? null, checkinT }
    }
    return { mode: 'armed', label: 'ARMED', title: 'Nobody is here.', detail: 'This space should be empty.', zone: null, checkinT }
  }
  const alert = state.alert ?? {}
  if (alert.state === 'check_on') {
    const where = ZONES[alert.zone] ? `in the ${ZONES[alert.zone]}` : 'in the room'
    const howLong = typeof alert.limit_s === 'number' ? ` for ${alert.limit_s} s` : ''
    return { mode: 'alert', label: 'NO-MOVEMENT ALERT', title: `No movement ${where}${howLong}.`, detail: 'A wave or a tap on reset clears it.', zone: ZONES[alert.zone] ?? null, checkinT }
  }
  const pred = state.pred
  if (!pred) {
    return { mode: 'waiting', label: 'GETTING READY', title: 'The radio is not ready yet.', detail: 'It is still being set up or recalibrating.', zone: null, checkinT }
  }
  if (!(pred.present && pred.kind === 'person')) {
    return { mode: 'calm', label: 'ALL GOOD', title: 'Nobody is in the room.', detail: '', zone: null, checkinT }
  }
  const counting = alert.state === 'counting' && typeof alert.still_s === 'number' && alert.still_s >= 1 // no "0 s" right after a check-in
  return {
    mode: 'calm',
    label: 'ALL GOOD',
    title: `Someone is in ${zoneName(pred.zone)}.`,
    detail: counting ? `No movement for ${Math.floor(alert.still_s)} s.` : pred.motion === 'moving' ? 'Moving.' : 'Standing still.',
    zone: ZONES[pred.zone] ?? null,
    checkinT,
  }
}

// The chime plays once, when the card turns into the alert or an intrusion. Staying there does not repeat it.
export function shouldChime(previousMode, mode) {
  return (mode === 'alert' || mode === 'intrusion') && previousMode !== mode
}

export function checkinText(checkinT, format = (t) => new Date(t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })) {
  return checkinT == null ? 'No check-in yet' : `Last check-in ${format(checkinT)}`
}

// The brain's socket, as on the main screen: same host, port 8765; ?ws=<url> overrides.
export function wsUrl(loc) {
  const override = new URLSearchParams(loc.search).get('ws')
  return override || `ws://${loc.hostname || '127.0.0.1'}:8765/ws`
}

// Mock states for ?mock=<name>, for looking at each card without a board.
const base = { v: 2, type: 'state', src: 'sim', health: { status: 'ok', blind: [], reason: null }, checkin: null }
const inZone = (zone, motion) => ({ present: true, kind: 'person', zone, zone_set: [zone], motion })
const idle = { state: 'none', zone: null, still_s: 0, limit_s: null }
export const MOCKS = {
  calm: { ...base, pred: inZone(2, 'moving'), alert: idle },
  counting: { ...base, pred: inZone(4, 'still'), alert: { state: 'counting', zone: 4, still_s: 7.2, limit_s: 10 } },
  alert: { ...base, pred: inZone(4, 'still'), alert: { state: 'check_on', zone: 4, still_s: 10.4, limit_s: 10 } },
  checkin: { ...base, pred: inZone(4, 'still'), alert: { state: 'counting', zone: 4, still_s: 0.6, limit_s: 10 }, checkin: { t: 1763149511000, link: 'pi5>unoq:wifi' } },
  empty: { ...base, pred: { present: false, kind: 'none', zone: 0, zone_set: [], motion: null }, alert: idle },
  blind: { ...base, health: { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' }, pred: null, alert: idle },
  armed: { ...base, armed: true, pred: { present: false, kind: 'none', zone: 0, zone_set: [], motion: null }, alert: idle },
  intrusion: { ...base, armed: true, pred: inZone(4, 'moving'), alert: idle },
}
