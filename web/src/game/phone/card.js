// What the caregiver's phone shows for a brain state. No DOM in here, so it can be tested with node.
// Message shapes come from CONTRACTS.md v2, section 5. Every number shown comes from the state.

import { deviceName, placeName, ZONES } from '../zones.js'

export { ZONES }
export const STALE_MS = 1000 // section 6: NO DATA when the last state is older than 1 s

export function isState(msg) {
  return Boolean(msg) && msg.v === 2 && msg.type === 'state'
}

export function isEvent(msg) {
  return Boolean(msg) && msg.v === 2 && msg.type === 'event' && typeof msg.kind === 'string'
}

function zoneName(z) {
  return ZONES[z] ? `the ${ZONES[z]} zone` : 'the room'
}

// "in the Chair zone", or "at the desk" for a zone named as a place.
function zoneWhere(z) {
  return placeName(z) ?? `in ${zoneName(z)}`
}

// The words of the title that take the person colour: the zone's name as the title says it.
function zoneWord(z) {
  return placeName(z) ?? ZONES[z] ?? null
}

// Armed mode (section 6) is the board's call, never the page's: the intrusion card comes only from the brain's
// intrusion event, and a passer-by only from its passed_by event. pred never raises either, so the phone in a
// judge's hand says what the big screen and the incident report say.
// What those events said, as the page keeps it: { intrusion: { id, zone, link } | null, passedBy: { zone, until } | null }.
export const PASSED_BY_MS = 5000
export function noEvents() {
  return { intrusion: null, passedBy: null }
}

// One message in -> { events, chime }. chime is true once per new intrusion (the same event id again is not new).
// The intrusion stays until disarmed or reset (or a state that is not armed, see followState). passed_by is one
// calm line that goes after PASSED_BY_MS and never chimes.
export function takeEvent(events, msg, now) {
  if (!isEvent(msg)) return { events, chime: false }
  const info = msg.info ?? {}
  const zone = Number.isInteger(info.zone) ? info.zone : null
  if (msg.kind === 'intrusion') {
    const id = `${msg.src}:${msg.id}`
    const link = typeof info.link === 'string' ? info.link : null
    return { events: { intrusion: { id, zone, link }, passedBy: null }, chime: events.intrusion?.id !== id }
  }
  if (msg.kind === 'passed_by') return { events: { ...events, passedBy: { zone, until: now + PASSED_BY_MS } }, chime: false }
  if (msg.kind === 'disarmed' || msg.kind === 'reset') return { events: noEvents(), chime: false }
  return { events, chime: false }
}

// A state that is not armed ends whatever the armed events said (a missing armed means false, section 5).
export function followState(events, state) {
  return isState(state) && state.armed !== true && (events.intrusion || events.passedBy) ? noEvents() : events
}

function passedWords(zone) {
  const name = ZONES[zone]
  if (!name) return 'Someone passed by.'
  if (placeName(zone)) return `Someone passed by ${placeName(zone)}.`
  return /^(left|right)$/i.test(name) ? `Someone passed by on the ${name.toLowerCase()}.` : `Someone passed by in ${zoneName(zone)}.`
}

// Section 6 Tamper: the devices silent while armed, by their nodes.json names. '' when there is none.
export function tamperText(state) {
  const silent = Array.isArray(state?.tamper) ? [...new Set(state.tamper)].map(deviceName) : []
  if (!silent.length) return ''
  const names = silent.length < 3 ? silent.join(' and ') : `${silent.slice(0, -1).join(', ')} and ${silent.at(-1)}`
  return `${names} unplugged while armed.`
}

// card(state, age of that state in ms, the events the page kept, now in ms)
//   -> { mode, label, title, detail, zone, checkinT, passedBy, tamper }
// mode: 'intrusion' | 'alert' | 'armed' | 'calm' | 'waiting' | 'blind' | 'nodata'. label is the word that goes with the colour.
// passedBy and tamper are the small lines under the card ('' when there is nothing to say).
export function card(state, ageMs, events = noEvents(), now = 0) {
  const checkinT = state?.checkin?.t ?? null
  if (!isState(state) || ageMs > STALE_MS) {
    return { mode: 'nodata', label: 'NO DATA', title: 'No data from the board.', detail: 'Waiting for the radio feed.', zone: null, checkinT: null, passedBy: '', tamper: '' }
  }
  const armed = state.armed === true
  const lines = { passedBy: '', tamper: armed ? tamperText(state) : '' }
  // The board raised an intrusion: it stays up until disarm or reset, through a blind sensor too.
  if (armed && events.intrusion) {
    const { zone, link } = events.intrusion
    const title = zone != null ? `Someone is ${zoneWhere(zone)}.` : link ? 'Someone is on a hall path.' : 'Someone is here.'
    return { mode: 'intrusion', label: 'INTRUSION', title, detail: 'This space should be empty.', zone: zoneWord(zone), checkinT, ...lines }
  }
  if (state.health?.status === 'blind') {
    return { mode: 'blind', label: 'SENSOR BLIND', title: 'The radio cannot read the room right now.', detail: 'This does not mean the room is empty.', zone: null, checkinT, ...lines }
  }
  // Armed (section 6): this space should be empty. Whatever pred says, the card stays "Armed." until the board
  // raises an intrusion; with no prediction it never says "all clear".
  if (armed) {
    if (!state.pred) return { mode: 'waiting', label: 'ARMED', title: 'The radio is not ready yet.', detail: 'It cannot say the space is empty.', zone: null, checkinT, ...lines }
    const passedBy = events.passedBy && now < events.passedBy.until ? passedWords(events.passedBy.zone) : ''
    return { mode: 'armed', label: 'ARMED', title: 'Armed.', detail: 'This space should be empty.', zone: null, checkinT, ...lines, passedBy }
  }
  const alert = state.alert ?? {}
  if (alert.state === 'check_on') {
    const where = placeName(alert.zone) ?? (ZONES[alert.zone] ? `in the ${ZONES[alert.zone]}` : 'in the room')
    const howLong = typeof alert.limit_s === 'number' ? ` for ${alert.limit_s} s` : ''
    return { mode: 'alert', label: 'NO-MOVEMENT ALERT', title: `No movement ${where}${howLong}.`, detail: 'A wave or a tap on reset clears it.', zone: zoneWord(alert.zone), checkinT, ...lines }
  }
  const pred = state.pred
  if (!pred) {
    return { mode: 'waiting', label: 'GETTING READY', title: 'The radio is not ready yet.', detail: 'It is still being set up or recalibrating.', zone: null, checkinT, ...lines }
  }
  if (!(pred.present && pred.kind === 'person')) {
    return { mode: 'calm', label: 'ALL GOOD', title: 'Nobody is in the room.', detail: '', zone: null, checkinT, ...lines }
  }
  const counting = alert.state === 'counting' && typeof alert.still_s === 'number' && alert.still_s >= 1 // no "0 s" right after a check-in
  return {
    mode: 'calm',
    label: 'ALL GOOD',
    title: `Someone is ${zoneWhere(pred.zone)}.`,
    detail: counting ? `No movement for ${Math.floor(alert.still_s)} s.` : pred.motion === 'moving' ? 'Moving.' : 'Standing still.',
    zone: zoneWord(pred.zone),
    checkinT,
    ...lines,
  }
}

// The no-movement chime plays once, when the card turns into the alert. Staying there does not repeat it.
// The intrusion chime comes from the event instead (takeEvent), so a feed that drops out and comes back
// does not ring a second time for the same intrusion.
export function shouldChime(previousMode, mode) {
  return mode === 'alert' && previousMode !== mode
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
const nobody = { present: false, kind: 'none', zone: 0, zone_set: [], motion: null }
const idle = { state: 'none', zone: null, still_s: 0, limit_s: null }
export const MOCKS = {
  calm: { ...base, pred: inZone(2, 'moving'), alert: idle },
  counting: { ...base, pred: inZone(4, 'still'), alert: { state: 'counting', zone: 4, still_s: 7.2, limit_s: 10 } },
  alert: { ...base, pred: inZone(4, 'still'), alert: { state: 'check_on', zone: 4, still_s: 10.4, limit_s: 10 } },
  checkin: { ...base, pred: inZone(4, 'still'), alert: { state: 'counting', zone: 4, still_s: 0.6, limit_s: 10 }, checkin: { t: 1763149511000, link: 'pi5>unoq:wifi' } },
  empty: { ...base, pred: nobody, alert: idle },
  blind: { ...base, health: { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' }, pred: null, alert: idle },
  armed: { ...base, armed: true, pred: nobody, alert: idle },
  intrusion: { ...base, armed: true, pred: inZone(4, 'moving'), alert: idle },
  passed: { ...base, armed: true, pred: nobody, alert: idle },
  tamper: { ...base, armed: true, health: { status: 'blind', blind: ['east>unoq:ble'], reason: 'rate' }, pred: null, alert: idle, tamper: ['east'] },
}
// The events a mock card stands on. pred never raises an intrusion, so the intrusion mock sets the event by hand.
export const MOCK_EVENTS = {
  intrusion: { intrusion: { id: 'mock:e1', zone: 4, link: null }, passedBy: null },
  passed: { intrusion: null, passedBy: { zone: 2, until: Infinity } },
}
