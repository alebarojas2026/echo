// Page wiring for the crowd game: the brain's state socket in, taps on the zone buttons out.
import { swap } from './fade.js'
import { compass, loadZones, zoneList } from './zones.js'
import { addRound, counts, emptyTally, isState, judge, load, resultText, save, status, tallyText, truthCmd, undo, wsUrl, ZONES } from './tally.js'

const $ = (id) => document.getElementById(id)
const tallyEl = $('tally')
const statusEl = $('status')
const resultEl = $('result')

// ?mock=ready|round|result|practice|blind shows one state without a board, for checking the look.
// A mock never reads or writes the stored tally.
const MOCK_LINKS = [{ id: 'east>pi5:ble', rate_hz: 9 }]
const MOCK_STATE = { v: 2, type: 'state', src: 'live', cam: 'off', links: MOCK_LINKS, health: { status: 'ok' },
  pred: { present: true, kind: 'person', zone: 4, zone_set: [4], motion: 'still' } }
const MOCKS = {
  ready: {},
  round: { tally: { found: 3, hidden: 2, rounds: ['found', 'hidden', 'found', 'found', 'hidden'] } },
  result: { tally: { found: 3, hidden: 2, rounds: ['found', 'hidden', 'found', 'found', 'hidden'] }, tap: 1 },
  practice: { state: { src: 'sim' } },
  blind: { state: { pred: null, health: { status: 'blind' } } },
}
const mock = MOCKS[new URLSearchParams(location.search).get('mock')]
const storage = mock ? { getItem: () => null, setItem: () => {} } : localStorage

let tally = mock?.tally ?? load(storage)
let state = mock ? { ...MOCK_STATE, ...mock.state } : null
let stateAt = performance.now()
let socket = null

function age() {
  if (mock) return 0
  return state ? performance.now() - stateAt : Infinity
}

// Zone names take the person colour; the rest of the sentence stays plain.
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const zoneNames = () => new RegExp(`(${Object.values(ZONES).map(escape).join('|')})`)
function showResult(text, outcome) {
  resultEl.dataset.outcome = outcome
  swap(resultEl, text, () => resultEl.replaceChildren(...text.split(zoneNames()).map((part, i) =>
    i % 2 ? Object.assign(document.createElement('span'), { className: 'zone', textContent: part }) : part)))
}

function showTally() {
  const n = counts(tally)
  swap($('found'), n.found)
  swap($('hidden'), n.hidden)
  for (const id of ['found', 'hidden']) $(id).toggleAttribute('data-empty', n[id] === '__')
  tallyEl.setAttribute('aria-label', tallyText(tally))
  tallyEl.dataset.found = tally.found
  tallyEl.dataset.hidden = tally.hidden
  $('undo').disabled = tally.rounds.length === 0
  $('reset').disabled = tally.rounds.length === 0
}

function showStatus() {
  const now = status(state, age())
  statusEl.dataset.kind = now.kind
  swap($('source'), now.source)
  swap($('cam'), now.cam)
  swap($('note'), now.note)
}

function play(zone) {
  const result = judge(state, age(), zone)
  tally = addRound(tally, result)
  save(storage, tally)
  showResult(resultText(result), result.outcome)
  showTally()
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(truthCmd(zone)))
}

function connect() {
  socket = new WebSocket(wsUrl(location))
  socket.onmessage = (event) => {
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }
    if (!isState(msg)) return
    state = msg
    stateAt = performance.now()
    showStatus()
  }
  socket.onclose = () => setTimeout(connect, 1000)
  socket.onerror = () => socket.close()
}

// The floor's buttons, one per zone, from nodes.json once it loads (the page starts with the contract's four).
function renderFloor() {
  const zones = zoneList()
  $('floor').replaceChildren(...zones.map(({ id, name, hint }) => {
    const button = Object.assign(document.createElement('button'), { type: 'button' })
    button.dataset.zone = id
    button.append(Object.assign(document.createElement('strong'), { textContent: name }),
      Object.assign(document.createElement('span'), { textContent: hint }))
    return button
  }))
  $('compass').replaceChildren(...compass().map((text) => Object.assign(document.createElement('span'), { textContent: text })))
  const ids = zones.map((z) => z.id)
  $('hint').textContent = `Tap the zone, or press ${ids.length > 1 ? `${Math.min(...ids)} to ${Math.max(...ids)}` : ids[0]}.`
}
$('floor').addEventListener('click', (event) => {
  const button = event.target.closest?.('[data-zone]')
  if (button) play(Number(button.dataset.zone))
})
document.addEventListener('keydown', (event) => {
  if (event.target.closest?.('input, textarea') || event.metaKey || event.ctrlKey || event.altKey) return
  if (ZONES[event.key]) play(Number(event.key))
})
$('undo').addEventListener('click', () => {
  tally = undo(tally)
  save(storage, tally)
  showResult('Last round taken back.', '')
  showTally()
})
$('reset').addEventListener('click', () => {
  if (!$('reset').dataset.armed) {
    $('reset').dataset.armed = '1'
    $('reset').textContent = 'Tap again to clear the tally'
    setTimeout(() => {
      delete $('reset').dataset.armed
      $('reset').textContent = 'Start over'
    }, 3000)
    return
  }
  tally = emptyTally()
  save(storage, tally)
  delete $('reset').dataset.armed
  $('reset').textContent = 'Start over'
  showResult('', '')
  showTally()
})

showTally()
showStatus()
function mockTap() {
  if (!mock?.tap) return
  const result = judge(state, 0, mock.tap)
  showResult(resultText(result), result.outcome)
}
mockTap()
loadZones().then((changed) => {
  if (!changed) return
  renderFloor()
  mockTap() // the mock's result in the zone names that just arrived
})
if (!mock) {
  setInterval(showStatus, 250)
  connect()
}
