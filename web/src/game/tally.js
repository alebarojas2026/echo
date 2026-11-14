// Rules for the "Can you hide from Wi-Fi?" crowd game. No DOM in here, so it can be tested with node.
// Message shapes come from CONTRACTS.md v2, section 5.

export const ZONES = { 1: 'Bed', 2: 'Chair', 3: 'Hall', 4: 'Bathroom' }
export const STALE_MS = 1000 // contract section 6: NO DATA when the last state is older than 1 s
export const STORE_KEY = 'radio-sight-hide-tally'

// The contract says to check v and type at runtime: only a v2 state message counts.
export function isState(msg) {
  return Boolean(msg) && msg.v === 2 && msg.type === 'state'
}

export function emptyTally() {
  return { found: 0, hidden: 0, rounds: [] }
}

// One round: someone stands in `truthZone`; did the radio have them there?
// outcome: 'found' | 'hidden' | 'no_data' | 'not_ready'. Only live rounds are counted.
export function judge(state, ageMs, truthZone) {
  if (!state || ageMs > STALE_MS) return { outcome: 'no_data', counted: false, guess: null }
  const pred = state.pred
  if (!pred) return { outcome: 'not_ready', counted: false, guess: null, blind: state.health?.status === 'blind' }
  const guess = pred.present && pred.kind === 'person' ? pred.zone : 0
  return { outcome: guess === truthZone ? 'found' : 'hidden', counted: state.src === 'live', guess, truth: truthZone }
}

export function addRound(tally, result) {
  if (!result.counted) return tally
  return {
    found: tally.found + (result.outcome === 'found' ? 1 : 0),
    hidden: tally.hidden + (result.outcome === 'hidden' ? 1 : 0),
    rounds: [...tally.rounds, result.outcome],
  }
}

export function undo(tally) {
  const last = tally.rounds.at(-1)
  if (!last) return tally
  return { ...tally, [last]: tally[last] - 1, rounds: tally.rounds.slice(0, -1) }
}

export function load(storage) {
  try {
    const t = JSON.parse(storage.getItem(STORE_KEY))
    const ok = t && Array.isArray(t.rounds) && t.rounds.every((r) => r === 'found' || r === 'hidden')
    if (!ok) return emptyTally()
    return { found: t.rounds.filter((r) => r === 'found').length, hidden: t.rounds.filter((r) => r === 'hidden').length, rounds: t.rounds }
  } catch {
    return emptyTally()
  }
}

export function save(storage, tally) {
  try {
    storage.setItem(STORE_KEY, JSON.stringify(tally))
  } catch {
    // private mode or a full disk: the tally still works until the page reloads
  }
}

export function tallyText(tally) {
  const total = tally.found + tally.hidden
  if (!total) return 'No rounds yet'
  return `Wi-Fi found ${tally.found} of ${total}. ${tally.hidden} hid.`
}

export function resultText(result) {
  const name = (z) => `the ${ZONES[z]} zone`
  const practice = result.counted ? '' : ' Practice round, not counted.'
  if (result.outcome === 'no_data') return 'No data from the board, so this round does not count.'
  if (result.outcome === 'not_ready') {
    return result.blind ? 'The sensor is blind right now, so this round does not count.' : 'The radio is not ready yet, so this round does not count.'
  }
  if (result.outcome === 'found') return `Found you in ${name(result.truth)}.${practice}`
  const looked = result.guess ? `Wi-Fi looked in ${name(result.guess)}` : 'Wi-Fi saw nobody'
  return `You hid! ${looked}, you were in ${name(result.truth)}.${practice}`
}

export function truthCmd(zone) {
  return { v: 2, type: 'cmd', cmd: 'truth', args: { zone } }
}

// The brain's socket is on the same host as the page, port 8765 (contract section 2). ?ws= overrides it.
export function wsUrl(loc) {
  const override = new URLSearchParams(loc.search).get('ws')
  return override || `ws://${loc.hostname || '127.0.0.1'}:8765/ws`
}
