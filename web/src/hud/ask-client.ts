export interface AskResponse {
  answer: string
  rows: Record<string, unknown>[]
  tool: string | null
  ms: number | null
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
    return { answer: 'No room records are loaded in this mock.', rows: [{ source: 'Mock event store', result: 'No records loaded' }], tool, ms: null }
  },
}
