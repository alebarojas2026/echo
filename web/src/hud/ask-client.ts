import { mockHistory } from './records'

export interface AskResponse {
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
export const mockAskClient: AskClient = {
  mode: 'mock',
  async ask(question, signal) {
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Cancelled', 'AbortError')) }
      const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 650)
      if (signal.aborted) abort()
      else signal.addEventListener('abort', abort, { once: true })
    })
    const index = examples.findIndex(example => example.toLowerCase() === question.trim().toLowerCase())
    if (index < 0) return { answer: 'I can answer: presence, stillness, and changes to the Wi-Fi link. Try one of the examples.', rows: [], tool: null, ms: null }
    const tool = ['presence', 'still_spans', 'link_history'][index]
    if (index === 0) {
      // The mock's own two minutes: the answer counts its rows, and the screen can replay them.
      const span = { from_t: Date.now() - 120_000, to_t: Date.now() }
      const present_s = mockHistory(span).rows.filter(row => row.present).length
      return { answer: `Mock records: someone was here for ${present_s} s of the last 2 minutes.`, rows: [{ source: 'Mock records', present_s }], tool, ms: null, span }
    }
    return { answer: 'No room records are loaded in this mock.', rows: [{ source: 'Mock event store', result: 'No records loaded' }], tool, ms: null }
  },
}
