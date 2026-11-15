import { mockHistory } from './records'

export const recentQuestion = 'what happened in the last five minutes'
export interface AskResponse {
  steps?: { tool: string; ms: number | null; rows: number | null }[]
  cites?: number[]
  chain_ok?: boolean
  answer: string
  rows: Record<string, unknown>[]
  tool: string | null
  ms: number | null
  /** Set when the answer is about a stretch of time, so the screen can offer a replay of it (#533). */
  span?: { from_t: number; to_t: number }
}
export interface AskClient {
  mode: 'mock' | 'board'
  ask(question: string, signal: AbortSignal): Promise<AskResponse>
}
export const examples = [
  'Was anyone here in the last 10 minutes?',
  'How long was the last person still?',
  'Why did the Wi-Fi link drop?',
]
export function makeMockAskClient(now: () => number | null): AskClient { return {
  mode: 'mock',
  async ask(question, signal) {
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Cancelled', 'AbortError')) }
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 650)
      if (signal.aborted) abort()
      else signal.addEventListener('abort', abort, { once: true })
    })
    if (question.trim().toLowerCase() === recentQuestion) {
      const end = now()
      if (end === null) throw new Error('Waiting for a board reading.')
      const rows = [{t:end-120000,text:'Someone arrived.',cites:[1]}, {t:end-30000,text:'They left the spot.',cites:[2]}]
      return {answer:'Someone arrived. They left the spot.',rows,tool:'story',ms:null,steps:[{tool:'Mock records',ms:null,rows:rows.length}],cites:[1,2],span:{from_t:end-300000,to_t:end}}
    }
    const index = examples.findIndex(example => example.toLowerCase() === question.trim().toLowerCase())
    if (index < 0) return { answer: 'I can answer: presence, stillness, and changes to the Wi-Fi link. Try one of the examples.', rows: [], tool: null, ms: null }
    const tool = ['presence', 'still_spans', 'link_history'][index]
    if (index === 0) {
      // The mock's own two minutes: the answer counts its rows, and the screen can replay them.
      const end = now()
      if (end === null) throw new Error('Waiting for the board time. Try again after a reading arrives.')
      const span = { from_t: end - 120_000, to_t: end }
      const present_s = mockHistory(span).rows.filter(row => row.present).length
      return { answer: `Mock records: someone was here for ${present_s} s of the last 2 minutes.`, rows: [{ source: 'Mock records', present_s }], tool, ms: null, span }
    }
    return { answer: 'No room records are loaded in this mock.', rows: [{ source: 'Mock event store', result: 'No records loaded' }], tool, ms: null }
  },
} }
export const mockAskClient = makeMockAskClient(() => null)

/** Real answers and their replay spans are stamped on the board itself. */
export const boardAskClient: AskClient = {
  mode: 'board',
  async ask(question, signal) {
    const response = await fetch('/ask', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ question }), signal })
    if (!response.ok) throw new Error('The board could not answer. Try again.')
    const value = await response.json() as AskResponse
    if (typeof value.answer !== 'string' || !Array.isArray(value.rows)) throw new Error('The board answer could not be read.')
    if (value.span && (!Number.isFinite(value.span.from_t) || !Number.isFinite(value.span.to_t) || value.span.to_t < value.span.from_t)) delete value.span
    return value
  },
}
