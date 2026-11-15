// Browser probe for the soak test: opens the screen once, never reloads it, and prints
// one JSON line every 500 ms with what a judge would see (NO DATA, SENSOR BLIND, zone, alert).
//   node lab/soak/probe.mjs http://127.0.0.1:8080/?src=ws [chrome executable]
// Rendering is forced onto the CPU (SwiftShader), so it never touches the GPU.
import { chromium } from 'playwright'

const [url, executablePath] = process.argv.slice(2)
const out = (o) => process.stdout.write(JSON.stringify({ t: Date.now(), ...o }) + '\n')

const browser = await chromium.launch({
  headless: true,
  executablePath: executablePath || undefined,
  args: ['--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--enable-precise-memory-info'],
})
const page = await browser.newPage({ viewport: { width: 960, height: 540 } })
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') out({ kind: 'console', level: m.type(), text: m.text().slice(0, 300) }) })
page.on('pageerror', (e) => out({ kind: 'pageerror', text: String(e).slice(0, 300) }))
page.on('crash', () => out({ kind: 'crash' }))

// Count what arrives on the page's own WebSocket, without changing what the app does with it.
await page.addInitScript(() => {
  const soak = (window.__soak = { states: 0, events: 0, last: null, opens: 0, closes: 0 })
  const Native = window.WebSocket
  window.WebSocket = class extends Native {
    constructor(...args) {
      super(...args)
      this.addEventListener('open', () => soak.opens++)
      this.addEventListener('close', () => soak.closes++)
      this.addEventListener('message', (e) => {
        const s = String(e.data)
        if (s.startsWith('{"v":2,"type":"state"')) { soak.states++; soak.last = performance.now() } else soak.events++
      })
    }
  }
})
await page.goto(url)
const gl = await page.evaluate(() => {
  const c = document.createElement('canvas').getContext('webgl2') || document.createElement('canvas').getContext('webgl')
  const ext = c && c.getExtension('WEBGL_debug_renderer_info')
  return c ? (ext ? c.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'webgl') : null
})
out({ kind: 'start', url, gl })

const read = () => page.evaluate(() => {
  const q = (id) => document.querySelector(`[data-testid="${id}"]`)
  // Shown = some element with that test id is visible and says something (works for a hidden
  // attribute and for a word that is set and cleared).
  const shown = (id) => [...document.querySelectorAll(`[data-testid="${id}"]`)]
    .some((el) => el.checkVisibility() && el.textContent.trim() !== '')
  const text = (id) => (q(id)?.textContent ?? null)
  const s = window.__soak
  return {
    // The judge layout says it in its headline instead.
    no_data: shown('no-data') || text('judge-headline') === 'No data',
    blind: shown('sensor-blind') || text('judge-headline') === 'Sensor blind',
    headline: text('judge-headline'), feed: document.getElementById('room')?.dataset.feed ?? null,
    badge: text('source-badge'), cam: text('cam-status'), zone: text('pred-zone'), pkind: text('pred-kind'),
    alert: text('alert-banner'), checkin: text('checkin-toast'), narr: text('narrator-text'),
    heap: performance.memory ? performance.memory.usedJSHeapSize : null, nodes: document.getElementsByTagName('*').length,
    states: s.states, events: s.events, age_ms: s.last === null ? null : Math.round(performance.now() - s.last),
    opens: s.opens, closes: s.closes,
  }
})
for (;;) {
  try { out({ kind: 'dom', ...(await read()) }) } catch (e) { out({ kind: 'probe_error', text: String(e).slice(0, 300) }) }
  await new Promise((r) => setTimeout(r, 500))
}
