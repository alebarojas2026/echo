// Page wiring for the caregiver's phone: the brain's state socket in, one big card out, a chime on the alert.
import { card, checkinText, isState, MOCKS, shouldChime, wsUrl } from './card.js'

const $ = (id) => document.getElementById(id)
const mock = MOCKS[new URLSearchParams(location.search).get('mock')]

let state = mock ?? null
let stateAt = performance.now()
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

// Text changes like the screen's: the old text fades out in 100 ms, the new one fades in over 140 ms,
// 40 ms later, in the same spot. Opacity and transform only. Nothing moves when the text is the same,
// and a ticking count (only its digits change) is swapped in place.
const shown = new Map()
function swap(el, text, render = () => { el.textContent = text }) {
  const before = shown.get(el)
  if (before === text) return
  shown.set(el, text)
  el.getAnimations().forEach((a) => a.cancel())
  const quiet = before === undefined || before.replace(/\d+/g, '#') === text.replace(/\d+/g, '#') ||
    matchMedia('(prefers-reduced-motion: reduce)').matches
  if (quiet) return render()
  el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, fill: 'forwards' }).finished.then(() => {
    if (shown.get(el) !== text) return
    render()
    el.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 140, delay: 40, fill: 'both' })
  }, () => {})
}

function show() {
  const c = card(state, mock ? 0 : performance.now() - stateAt)
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
    state = msg
    stateAt = performance.now()
    show()
  }
  socket.onclose = () => setTimeout(connect, 1000)
  socket.onerror = () => socket.close()
}

show()
if (!mock) {
  setInterval(show, 250) // so NO DATA appears when the feed goes quiet
  connect()
}
