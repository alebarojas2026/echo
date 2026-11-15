import './privacy.css'

type Reading = { ok: true; images: number; bytes_out: number; since_t: number; t: number }
const listeners = new Set<() => void>()
let reading: Reading | null = null
let timer: ReturnType<typeof setInterval> | undefined
let request: AbortController | null = null
let changedAt = 0
let reason = 'Privacy meter has not answered.'

function valid(value: unknown): value is Reading {
  if (!value || typeof value !== 'object') return false
  const row = value as Reading
  return row.ok === true && [row.images, row.bytes_out, row.since_t, row.t].every(n => Number.isSafeInteger(n) && n >= 0) && row.t >= row.since_t
}
const notify = () => listeners.forEach(fn => fn())
async function poll() {
  if (request) return
  const controller = request = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 2000)
  try {
    const response = await fetch('/privacy', { cache: 'no-store', signal: controller.signal })
    const value: unknown = response.ok ? await response.json() : null
    if (controller.signal.aborted) return
    if (valid(value)) {
      if (!reading || value.t !== reading.t || value.since_t !== reading.since_t) changedAt = performance.now()
      reading = value
      reason = 'The privacy reading stopped updating.'
    } else {
      reading = null
      reason = value && typeof value === 'object' && 'why' in value ? String(value.why) : 'The privacy meter could not be read.'
    }
  } catch {
    if (request !== controller) return
    reading = null
    reason = 'The privacy meter could not be reached.'
  } finally {
    clearTimeout(timeout)
    if (request === controller) request = null
    notify()
  }
}

export function mountPrivacyLine(host: HTMLElement) {
  const line = document.createElement('div')
  line.className = 'privacy-line'
  line.innerHTML = '<p data-testid="privacy-values"></p><p data-testid="privacy-duration"></p>'
  host.append(line)
  const values = line.querySelector<HTMLElement>('[data-testid="privacy-values"]')!
  const duration = line.querySelector<HTMLElement>('[data-testid="privacy-duration"]')!
  const paint = () => {
    const current = reading && performance.now() - changedAt < 3000 ? reading : null
    values.textContent = current ? `${current.images} images stored · ${current.bytes_out} bytes sent out` : 'privacy meter not running'
    values.dataset.tone = current && (current.images !== 0 || current.bytes_out !== 0) ? 'fault' : ''
    const seconds = current ? Math.floor((current.t - current.since_t) / 1000) : 0
    duration.textContent = current ? `Counting for ${Math.floor(seconds / 60)} min ${seconds % 60} s` : ''
    duration.style.visibility = current ? 'visible' : 'hidden'
    line.dataset.reason = current ? '' : reason
  }
  listeners.add(paint)
  paint()
  if (!timer) { void poll(); timer = setInterval(() => { notify(); void poll() }, 1000) }
  return () => {
    listeners.delete(paint); line.remove()
    if (!listeners.size) { clearInterval(timer); timer = undefined; request?.abort(); request = null; reading = null }
  }
}
