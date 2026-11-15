// Page wiring for the caregiver's phone: the brain's state socket in, one big card out, a chime on the alert.
import { swap } from '../fade.js'
import { card, checkinText, HOLD_OF, isState, MOCKS, personHeld, shouldChime, wsUrl } from './card.js'
import { loadZones } from '../zones.js'

const $ = (id) => document.getElementById(id)
const mock = MOCKS[new URLSearchParams(location.search).get('mock')]

let state = mock ?? null
let stateAt = performance.now()
let mode
let audio = null
const people = [] // was a person in each of the last states? (the intrusion waits for a majority)

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

function show() {
  const c = card(state, mock ? 0 : performance.now() - stateAt, mock ? true : personHeld(people))
  if (shouldChime(mode, c.mode)) {
    chime()
    // Browsers only vibrate after a tap on the page, and iPhone never does.
    if (navigator.userActivation?.hasBeenActive ?? true) navigator.vibrate?.([200, 100, 200])
  }
  mode = c.mode
  document.body.dataset.mode = c.mode
  swap($('label'), c.label)
  // The zone name takes the person colour; the rest of the sentence stays plain.
  const [before, after] = c.zone ? c.title.split(c.zone) : [c.title, '']
  swap($('title'), c.title, () => $('title').replaceChildren(before, ...(c.zone ? [Object.assign(document.createElement('span'), { className: 'zone', textContent: c.zone }), after] : [])))
  swap($('detail'), c.detail)
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
  socket.onmessage = (event) => {
    let msg
    try {
      msg = JSON.parse(event.data)
    } catch {
      return
    }
    if (!isState(msg)) return
    people.push(Boolean(msg.pred?.present && msg.pred.kind === 'person'))   // one per state, the last 10 kept
    if (people.length > HOLD_OF) people.shift()
    state = msg
    stateAt = performance.now()
    show()
  }
  socket.onclose = () => setTimeout(connect, 1000)
  socket.onerror = () => socket.close()
}

show()
loadZones().then((changed) => changed && show()) // the zone names from nodes.json
if (!mock) {
  setInterval(show, 250) // so NO DATA appears when the feed goes quiet
  connect()
}
