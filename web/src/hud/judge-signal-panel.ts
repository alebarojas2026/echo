import type { StateMsg } from '../room/contract'
import { NOTES, SignalHistory, WINDOW_MS, formatDrop, traceRuns, traceStatus, type Point } from './signal-trace'
import './signal.css'

// The signal trace on the main screen (a compact strip above the proof tiles) and on the arrival screen (a wide
// band under the headline). Both draw the same history; see signal-trace.ts for what a point is.

const NUMBER_EVERY_MS = 250
const FLOOR_DB = 8 // the scale shows at least this much drop, and grows when a reading goes deeper

interface Row { el: HTMLElement; canvas: HTMLCanvasElement; value: HTMLElement; w: number; h: number }

function createView(variant: 'strip' | 'arrival') {
  const el = document.createElement('section')
  el.className = 'signal'
  el.dataset.variant = variant
  el.dataset.testid = `signal-${variant}`
  el.setAttribute('aria-label', 'Radio signal, last 10 seconds')
  el.innerHTML = `<header><span>${variant === 'arrival' ? 'Radio signal through the space' : 'Radio signal'}</span><span>last 10 s</span></header>
    <div class="signal-rows"></div><p class="signal-note" data-testid="signal-note" hidden></p>`
  const rowsEl = el.querySelector<HTMLElement>('.signal-rows')!
  const note = el.querySelector<HTMLElement>('.signal-note')!
  let rows: Row[] = []
  let colours: Record<'link' | 'person' | 'edge', string> | null = null
  let scale = FLOOR_DB
  let lastDraw = 0
  const sized = new ResizeObserver(() => rows.forEach((row) => { row.w = 0 }))
  return {
    el,
    rows: () => rows,
    setSides(history: SignalHistory) {
      sized.disconnect()
      rowsEl.replaceChildren()
      rowsEl.dataset.count = String(history.sides.length)
      rows = history.sides.map((side) => {
        const row = document.createElement('div')
        row.className = 'signal-row'
        row.dataset.testid = 'signal-row'
        row.dataset.zone = String(side.zone)
        row.dataset.links = side.links.join(',')
        row.dataset.primary = side.primary ?? ''
        row.innerHTML = '<span class="signal-name"></span><canvas aria-hidden="true"></canvas><span class="signal-value" data-testid="signal-value"></span>'
        row.querySelector('.signal-name')!.textContent = side.name
        rowsEl.append(row)
        const canvas = row.querySelector('canvas')!
        sized.observe(canvas)
        return { el: row, canvas, value: row.querySelector<HTMLElement>('.signal-value')!, w: 0, h: 0 }
      })
    },
    setNote(text: string) {
      note.textContent = text
      note.hidden = !text
      rowsEl.hidden = !!text
    },
    draw(history: SignalHistory, now: number) {
      if (!el.isConnected || rowsEl.hidden || !rowsEl.offsetParent) return
      const css = getComputedStyle(el)
      colours ??= { link: css.getPropertyValue('--link').trim(), person: css.getPropertyValue('--person').trim(), edge: css.getPropertyValue('--edge').trim() }
      const all = rows.map((_, i) => {
        const side = history.sides[i]
        return side.traces?.map(trace => ({...trace, runs:traceRuns(history.samples, i, now, trace.id)})) ?? [{id:'',width:3,runs:traceRuns(history.samples,i,now)}]
      })
      let peak = 0
      for (const paths of all) for (const {runs} of paths) for (const run of runs) for (const p of run) if (p.age <= WINDOW_MS && p.drop > peak) peak = p.drop
      const target = Math.max(FLOOR_DB, Math.ceil(peak + 1))
      scale += (target - scale) * Math.min(1, (now - lastDraw) / 300)
      lastDraw = now
      const ratio = window.devicePixelRatio || 1
      rows.forEach((row, i) => {
        if (!row.w) {
          row.w = row.canvas.clientWidth
          row.h = row.canvas.clientHeight
          row.canvas.width = Math.round(row.w * ratio)
          row.canvas.height = Math.round(row.h * ratio)
        }
        const { w, h } = row
        const ctx = row.canvas.getContext('2d')
        if (!ctx || !w) return
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
        ctx.clearRect(0, 0, w, h)
        const pad = 6
        const zero = (variant === 'arrival' ? 28 : 17) + 0.5 // the baseline (no drop), level with the middle of the side's name
        const x = (p: Point) => w - pad - (p.age / WINDOW_MS) * (w - pad)
        const y = (p: Point) => Math.min(h - pad, Math.max(pad, zero + (p.drop / scale) * (h - pad - zero)))
        ctx.lineWidth = 1
        ctx.strokeStyle = colours!.edge
        ctx.beginPath()
        ctx.moveTo(0, zero)
        ctx.lineTo(w, zero)
        ctx.stroke()
        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'
        const paths = [...all[i]].sort((a,b)=>a.width-b.width)
        for (const {width,runs} of paths) {
          ctx.lineWidth = width
          for (const present of [false, true]) {
            ctx.strokeStyle = present ? colours!.person : colours!.link
            ctx.beginPath()
            for (const run of runs) {
              for (let k = 1; k < run.length; k++) {
                if (run[k].present !== present) continue
                ctx.moveTo(x(run[k - 1]), y(run[k - 1]))
                ctx.lineTo(x(run[k]), y(run[k]))
              }
            }
            ctx.stroke()
          }
        }
        const main = paths.find(trace => trace.id === history.sides[i].primary) ?? paths.at(-1)
        const pen = main?.runs.at(-1)?.at(-1)
        if (pen && pen.age === 0) {
          ctx.fillStyle = pen.present ? colours!.person : colours!.link
          ctx.beginPath()
          ctx.arc(x(pen), y(pen), 5, 0, Math.PI * 2)
          ctx.fill()
        }
        const drawn = String(paths.reduce((sum,trace)=>sum+trace.runs.length,0))
        if (row.el.dataset.runs !== drawn) row.el.dataset.runs = drawn
      })
    },
  }
}

export function mountPanel(root: HTMLElement) {
  const history = new SignalHistory()
  const strip = createView('strip')
  const arrival = createView('arrival')
  const views = [strip, arrival]
  root.replaceWith(strip.el)
  let placed = false
  const place = () => {
    // The strip sits just above the proof tiles, so it stays in one place while the cards above it come and go.
    const footer = strip.el.closest('.judge')?.querySelector(':scope > footer')
    if (footer && strip.el.nextElementSibling !== footer) footer.before(strip.el)
    // The arrival screen is built after the panels; the band goes under its headline.
    const message = document.querySelector('.hud-arrival .arrival-message')
    if (message && !arrival.el.isConnected) message.after(arrival.el)
    placed = !!footer && !!message
  }
  let sidesKey = ''
  let numbersAt = -Infinity
  let frame = requestAnimationFrame(function tick(now) {
    views.forEach((view) => view.draw(history, now))
    frame = requestAnimationFrame(tick)
  })
  return {
    update(state: StateMsg | null, stale: boolean) {
      if (!placed) place()
      history.refreshSides()
      const key = JSON.stringify(history.sides)
      if (key !== sidesKey) {
        sidesKey = key
        views.forEach((view) => view.setSides(history))
      }
      const now = performance.now()
      // A replay plays saved seconds, and the records hold no link readings: the live trace is not shown over it.
      const replayed = state?.src === 'replay'
      if (state && !stale && !replayed) history.push(state, now)
      const status = traceStatus(state, stale, history.sides)
      const latest = history.samples.at(-1)
      const fresh = !stale && !!latest && now - latest.t < 1000
      const numbers = now - numbersAt >= NUMBER_EVERY_MS
      if (numbers) numbersAt = now
      for (const view of views) {
        view.el.hidden = !history.sides.length || replayed
        view.el.dataset.status = status
        view.setNote(status === 'ok' || status === 'no-data' ? '' : NOTES[status])
        view.rows().forEach((row, i) => {
          const drop = fresh ? latest!.drop[i] : null
          row.el.dataset.present = String(fresh && latest!.present[i] && drop !== null)
          const signal = !fresh ? 'no-data' : drop === null ? 'none' : 'ok'
          // The number is rewritten four times a second, and at once when the reading comes or goes.
          if (!numbers && row.el.dataset.signal === signal) return
          row.el.dataset.signal = signal
          row.value.textContent = !fresh ? 'no data' : drop === null ? 'no signal' : formatDrop(drop)
        })
      }
    },
    dispose() {
      cancelAnimationFrame(frame)
      views.forEach((view) => view.el.remove())
    },
  }
}
