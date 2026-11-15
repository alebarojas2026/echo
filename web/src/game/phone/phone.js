// Page wiring for the caregiver's phone: the brain's socket in (states and events), one big card out, a chime on
// the alert and on the board's intrusion event.
import { swap } from '../fade.js'
import { card, checkinText, followState, isState, MOCK_EVENTS, MOCKS, noEvents, shouldChime, takeEvent, wsUrl } from './card.js'
import { loadZones } from '../zones.js'

const $ = (id) => document.getElementById(id)
const mockName = new URLSearchParams(location.search).get('mock')
const mock = MOCKS[mockName]

let state = mock ?? null
let stateAt = performance.now()
// The armed events the page has seen (card.js). A phone that opens the page after an intrusion has not seen it:
// the state carries no intrusion, so it shows "Armed." until the board sends the next event, and never guesses.
let events = (mock && MOCK_EVENTS[mockName]) ?? noEvents()
let mode
let audio = null

// Two soft tones, made in the browser: no sound file to load or store.
function chime() {
  if (!audio) return
  const now = audio.currentTime
  for (const [i, hz] of [660, 880].entries()) {
    const tone = audio.createOscillator()
    const gain = audio.createGain()
    tone.frequency.value = hz
    gain.gain.setValueAtTime(0.0001, now + i * 0.28)
    gain.gain.exponentialRampToValueAtTime(0.4, now + i * 0.28 + 0.03)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.28 + 0.6)
    tone.connect(gain).connect(audio.destination)
    tone.start(now + i * 0.28)
    tone.stop(now + i * 0.28 + 0.65)
  }
}

function ring() {
  chime()
  // Browsers only vibrate after a tap on the page, and iPhone never does.
  if (navigator.userActivation?.hasBeenActive ?? true) navigator.vibrate?.([200, 100, 200])
}

function line(el, text) {
  swap(el, text)
  el.dataset.has = text ? 'yes' : 'no'
}

function show() {
  const c = card(state, mock ? 0 : performance.now() - stateAt, events, mock ? 0 : performance.now())
  if (shouldChime(mode, c.mode)) ring()
  mode = c.mode
  document.body.dataset.mode = c.mode
  swap($('label'), c.label)
  // The zone name takes the person colour; the rest of the sentence stays plain.
  const [before, after] = c.zone ? c.title.split(c.zone) : [c.title, '']
  swap($('title'), c.title, () => $('title').replaceChildren(before, ...(c.zone ? [Object.assign(document.createElement('span'), { className: 'zone', textContent: c.zone }), after] : [])))
  swap($('detail'), c.detail)
  line($('passed'), c.passedBy)
  line($('tamper'), c.tamper)
  swap($('checkin'), checkinText(c.checkinT))
  $('checkin').dataset.has = c.checkinT == null ? 'no' : 'yes'
}

// iPhone only lets a page make sound after a tap, so sound starts with this button.
$('sound').addEventListener('click', async () => {
  audio ??= new (window.AudioContext ?? window.webkitAudioContext)()
  await audio.resume()
  chime()
  $('sound').textContent = 'Sound is on'
  $('sound').disabled = true
})

function connect() {
  const socket = new WebSocket(wsUrl(location))
  socket.onmessage = (message) => {
    let msg
    try {
      msg = JSON.parse(message.data)
    } catch {
      return
    }
    if (isState(msg)) {
      state = msg
      stateAt = performance.now()
      events = followState(events, msg)
    } else {
      const next = takeEvent(events, msg, performance.now())
      events = next.events
      if (next.chime && state?.armed === true) ring()
    }
    show()
  }
  socket.onclose = () => setTimeout(connect, 1000)
  socket.onerror = () => socket.close()
}

show()
loadZones().then((changed) => changed && show()) // the zone and device names from nodes.json
if (!mock) {
  setInterval(show, 250) // so NO DATA appears when the feed goes quiet, and a passed-by line goes after its time
  connect()
}
