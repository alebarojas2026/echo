// Page wiring for the crowd game: the brain's state socket in, taps on the zone buttons out.
import { addRound, emptyTally, judge, load, resultText, save, STALE_MS, tallyText, truthCmd, undo, wsUrl } from './tally.js'

const $ = (id) => document.getElementById(id)
const tallyEl = $('tally')
const statusEl = $('status')
const resultEl = $('result')

let tally = load(localStorage)
let state = null
let stateAt = 0
let socket = null

function age() {
  return state ? performance.now() - stateAt : Infinity
}

function showTally() {
  tallyEl.textContent = tallyText(tally)
  tallyEl.dataset.found = tally.found
  tallyEl.dataset.hidden = tally.hidden
  $('undo').disabled = tally.rounds.length === 0
  $('reset').disabled = tally.rounds.length === 0
}

function showStatus() {
  let text = 'Ready'
  let kind = 'ok'
  if (age() > STALE_MS) [text, kind] = ['NO DATA', 'off']
  else if (!state.pred) [text, kind] = [state.health?.status === 'blind' ? 'SENSOR BLIND' : 'Radio not ready', 'off']
  else if (state.src !== 'live') [text, kind] = [`Practice (${state.src}): rounds are not counted`, 'practice']
  statusEl.textContent = text
  statusEl.dataset.kind = kind
}

function play(zone) {
  const result = judge(state, age(), zone)
  tally = addRound(tally, result)
  save(localStorage, tally)
  resultEl.textContent = resultText(result)
  resultEl.dataset.outcome = result.outcome
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
    if (msg?.type !== 'state') return
    state = msg
    stateAt = performance.now()
    showStatus()
  }
  socket.onclose = () => setTimeout(connect, 1000)
  socket.onerror = () => socket.close()
}

for (const button of document.querySelectorAll('[data-zone]')) {
  button.addEventListener('click', () => play(Number(button.dataset.zone)))
}
document.addEventListener('keydown', (event) => {
  if (event.target.closest?.('input, textarea') || event.metaKey || event.ctrlKey || event.altKey) return
  if (['1', '2', '3', '4'].includes(event.key)) play(Number(event.key))
})
$('undo').addEventListener('click', () => {
  tally = undo(tally)
  save(localStorage, tally)
  resultEl.textContent = 'Last round taken back.'
  resultEl.dataset.outcome = ''
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
  save(localStorage, tally)
  delete $('reset').dataset.armed
  $('reset').textContent = 'Start over'
  resultEl.textContent = ''
  showTally()
})

showTally()
showStatus()
setInterval(showStatus, 250)
connect()
