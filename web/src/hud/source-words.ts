import type { StateMsg } from '../room/contract'
export function sourceWords(state: StateMsg | null) {
  if (state?.src === 'sim') return 'Simulated'
  if (state?.src === 'replay') return 'Replay'
  return state?.links.some(link => (link.rate_hz ?? 0) > 0) ? 'Live' : 'No radio'
}
