import { hudLayout } from './layout'

// The board's own records, as its web server gives them (contract issue #533): GET /history and GET /report.
// Until the board serves them the screen reads a mock with the same shapes, and says so.

export interface Span { from_t: number; to_t: number }

/** One saved second, exactly as the board saved it. A second with no row was not recorded. */
export interface HistoryRow {
  t: number
  /** null: the brain did not know then (blind, no model). Never read as false. */
  present: boolean | null
  zone: number | null
  zone_set: number[]
  motion: 'moving' | 'still' | null
  armed: boolean
  alert: boolean
  health: 'ok' | 'degraded' | 'blind'
  tamper: string[]
}

export interface History extends Span { step_s: number; rows: HistoryRow[] }

export interface Report {
  armed_from_t: number
  armed_to_t: number | null
  intrusions: ({ t: number; zone: number } | { t: number; link: string })[]
  present_s: number
  passed_by: number | null
  tamper: { t: number; node: string }[]
  blind_s: number
  text: string
  rows: number
  ms: number | null
}

export interface RecordsClient {
  mode: 'mock' | 'board'
  history(span: Span, signal?: AbortSignal): Promise<History>
  report(span?: Span, signal?: AbortSignal): Promise<Report>
}

/** The most the board returns in one call. */
export const MAX_SPAN_MS = 30 * 60_000

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal, cache: 'no-store', headers: { accept: 'application/json' } })
  if (!response.ok) throw new Error(`${url}: ${response.status}`)
  return (await response.json()) as T
}

export const boardRecords: RecordsClient = {
  mode: 'board',
  history: ({ from_t, to_t }, signal) => get<History>(`/history?from_t=${Math.round(from_t)}&to_t=${Math.round(to_t)}`, signal),
  report: (span, signal) => get<Report>(span ? `/report?from_t=${Math.round(span.from_t)}&to_t=${Math.round(span.to_t)}` : '/report', signal),
}

/**
 * A made-up stretch for building the screen without the board, in the board's shape: an empty space, one visit
 * that walks in and then stands still, seven seconds that were never saved, and eight where the sensor did not
 * know. The screen labels everything read from here as a mock.
 */
export function mockHistory({ from_t, to_t }: Span): History {
  const start = Math.ceil(from_t / 1000) * 1000
  const zones = hudLayout.zones.map((zone) => zone.id)
  const rows: HistoryRow[] = []
  for (let t = start, i = 0; t <= to_t; t += 1000, i++) {
    const row: HistoryRow = { t, present: false, zone: 0, zone_set: [], motion: null, armed: false, alert: false, health: 'ok', tamper: [] }
    if (i >= 45 && i < 52) continue
    if (i >= 15 && i < 45) {
      const zone = i < 24 ? zones[0] : zones.at(-1)!
      Object.assign(row, { present: true, zone, zone_set: [zone], motion: i < 28 ? 'moving' : 'still' })
    }
    if (i >= 60 && i < 68) Object.assign(row, { present: null, zone: null, health: 'blind' })
    rows.push(row)
  }
  return { from_t, to_t, step_s: 1, rows }
}

export const mockRecords: RecordsClient = {
  mode: 'mock',
  history: async (span) => mockHistory(span),
  report: async () => { throw new Error('no mock report') },
}

/** ?records=board|mock picks one; otherwise the board's records go with the board's feed. */
export function recordsClient(feedSource: string | undefined, params = new URLSearchParams(location.search)): RecordsClient {
  const pick = params.get('records') ?? (feedSource === 'ws' ? 'board' : 'mock')
  return pick === 'board' ? boardRecords : mockRecords
}

/** A replayed second: its row, or null when nothing was saved for it. */
export interface Second { t: number; row: HistoryRow | null }
export type SecondKind = 'record' | 'unknown' | 'none'

/** Every second of the span that has a row before or at it, oldest first. A missing second stays null. */
export function seconds(rows: readonly HistoryRow[]): Second[] {
  const sorted = [...rows].sort((a, b) => a.t - b.t)
  if (!sorted.length) return []
  const t0 = sorted[0].t
  const count = Math.round((sorted.at(-1)!.t - t0) / 1000) + 1
  const out: Second[] = Array.from({ length: count }, (_, i) => ({ t: t0 + i * 1000, row: null }))
  for (const row of sorted) out[Math.round((row.t - t0) / 1000)].row = row
  return out
}

export function secondKind(second: Second | undefined): SecondKind {
  return !second?.row ? 'none' : second.row.present === null ? 'unknown' : 'record'
}

/** The words for a second that cannot be shown as a room: never an empty room for either. */
export const KIND_WORDS: Record<Exclude<SecondKind, 'record'>, [string, string]> = {
  none: ['No record', 'Nothing was saved for this second.'],
  unknown: ['Sensor did not know', 'The radio could not tell at this moment.'],
}

/** "2:14 PM", in the screen's own time zone. */
export function clockTime(t: number): string {
  return new Date(t).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}
