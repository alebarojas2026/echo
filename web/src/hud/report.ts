import type { Feed } from '../room/feed'
import { linkName, zoneName } from './layout'
import { clockTime, type RecordsClient, type Report, type Span } from './records'
import './report.css'

const number = (n: unknown) => typeof n === 'number' && Number.isFinite(n) && n >= 0 ? String(n) : '__'
export function mountIncidentReport(feed: Feed | null, records: RecordsClient, replay: (span: Span) => void) {
  const card = document.createElement('dialog')
  card.className = 'incident-report'
  card.setAttribute('aria-labelledby', 'report-title')
  card.innerHTML = `<header><h2 id="report-title">Incident report</h2><button type="button" data-action="close">Close</button></header>
    <p data-testid="report-status" role="status"></p><div class="report-result" hidden>
    <p data-testid="report-text"></p><dl data-testid="report-facts"></dl><ul data-testid="report-intrusions"></ul>
    <p data-testid="report-origin"></p><p data-testid="report-time"></p></div>
    <button type="button" data-action="retry" hidden>Try again</button>`
  document.body.append(card)
  const find = <T extends HTMLElement>(selector: string) => card.querySelector<T>(selector)!
  const status = find('[data-testid="report-status"]'), result = find('.report-result'), retry = find<HTMLButtonElement>('[data-action="retry"]')
  let controller: AbortController | undefined
  let generation = 0
  const seen = new Set<string>()
  const close = () => { generation++; controller?.abort(); card.close() }
  find<HTMLButtonElement>('[data-action="close"]').onclick = close
  card.addEventListener('cancel', event => { event.preventDefault(); close() })
  const show = async () => {
    controller?.abort()
    const current = ++generation
    const request = controller = new AbortController()
    const timeout = setTimeout(() => request.abort(), 12000)
    if (!card.open) card.showModal()
    result.hidden = true; retry.hidden = true
    status.textContent = 'Reading the report from the board…'
    try {
      const report: Report | null = await records.report(undefined, request.signal)
      if (current !== generation) return
      if (!report) { status.textContent = 'No report for this stretch.'; return }
      if (typeof report.text !== 'string' || !Array.isArray(report.intrusions) || !Array.isArray(report.tamper)) throw new Error('Invalid report')
      status.textContent = records.mode === 'mock' ? 'Mock report' : ''
      find('[data-testid="report-text"]').textContent = report.text
      const facts = find('[data-testid="report-facts"]')
      facts.replaceChildren()
      const time = (t: number | null) => t != null && Number.isFinite(t) ? clockTime(t) : '__'
      for (const [label, value] of [
        ['Armed', time(report.armed_from_t)], ['Disarmed', time(report.armed_to_t)],
        ['Intrusions', report.intrusions.length], ['Someone present', `${number(report.present_s)} s`],
        ['Passed by', number(report.passed_by)], ['Device interruptions', report.tamper.length],
        ['Sensor blind', `${number(report.blind_s)} s`], ['Saved records', number(report.rows)],
      ]) {
        const pair = document.createElement('div'), term = document.createElement('dt'), count = document.createElement('dd')
        term.textContent = String(label); count.textContent = String(value); pair.append(term, count); facts.append(pair)
      }
      const intrusions = find('[data-testid="report-intrusions"]')
      intrusions.replaceChildren()
      report.intrusions.forEach((event, index) => {
        const row = document.createElement('li'), words = document.createElement('span'), button = document.createElement('button')
        words.textContent = `${time(event.t)} · ${'zone' in event ? zoneName(event.zone) : linkName(event.link)}`
        button.type = 'button'; button.textContent = 'Replay'; button.setAttribute('aria-label', `Replay intrusion ${index + 1}`)
        button.disabled = !Number.isFinite(event.t) || !Number.isFinite(report.armed_from_t)
        button.onclick = () => { close(); replay({ from_t: Math.max(report.armed_from_t, event.t - 10000), to_t: Math.min(report.armed_to_t ?? event.t + 20000, event.t + 20000) }) }
        row.append(words, button); intrusions.append(row)
      })
      find('[data-testid="report-time"]').textContent = `Report time: ${number(report.ms)} ms`
      const origin = find('[data-testid="report-origin"]')
      origin.textContent = records.mode === 'mock' ? 'Mock report · __ bytes out' : 'Written on the board · privacy meter not running'
      result.hidden = false
      if (records.mode === 'board') {
        try {
          const response = await fetch('/privacy', { cache: 'no-store', signal: request.signal })
          const privacy = response.ok ? await response.json() : null
          if (current !== generation) return
          if (privacy?.ok === true && number(privacy.bytes_out) !== '__') {
            origin.textContent = `Written on the board · ${privacy.bytes_out} bytes out`
            origin.dataset.tone = privacy.bytes_out === 0 ? '' : 'fault'
          }
        } catch { /* The report remains readable when the privacy meter is unavailable. */ }
      }
    } catch {
      if (current !== generation) return
      status.textContent = 'The report could not be read. Try again.'; retry.hidden = false
    } finally { clearTimeout(timeout) }
  }
  retry.onclick = () => void show()
  const off = feed?.onEvent(event => {
    if (['armed', 'intrusion', 'tamper', 'reset'].includes(event.kind)) close()
    if (event.kind !== 'disarmed') return
    const key = `${event.src}:${event.id}`
    if (seen.has(key)) return
    seen.add(key); void show()
  })
  return () => { close(); off?.(); card.remove() }
}
