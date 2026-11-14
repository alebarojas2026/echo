import type { CmdName, StateMsg } from './contract'
import { mockState } from './mock'

// The one place screen data comes from. The room and the hud panels both read this.

export type FeedSource = 'mock' | 'ws'

export interface FeedSnapshot {
  state: StateMsg | null
  /** performance.now() when the last state arrived, or null before the first one. */
  receivedAt: number | null
  source: FeedSource
}

export interface Feed {
  readonly source: FeedSource
  current(): FeedSnapshot
  /** Called with every new snapshot. Returns an unsubscribe function. */
  subscribe(fn: (snap: FeedSnapshot) => void): () => void
  send(cmd: CmdName, args?: Record<string, unknown>): void
}

type Listener = (snap: FeedSnapshot) => void

function createMockFeed(): Feed {
  const listeners = new Set<Listener>()
  let seq = 0
  let snap: FeedSnapshot = { state: null, receivedAt: null, source: 'mock' }

  const tick = () => {
    seq += 1
    snap = { state: mockState(seq), receivedAt: performance.now(), source: 'mock' }
    for (const fn of listeners) fn(snap)
  }
  tick()
  setInterval(tick, 100)

  return {
    source: 'mock',
    current: () => snap,
    subscribe(fn) {
      listeners.add(fn)
      fn(snap)
      return () => listeners.delete(fn)
    },
    send(cmd, args = {}) {
      console.info('mock feed: cmd', cmd, args)
    },
  }
}

export function createFeed(_params = new URLSearchParams(location.search)): Feed {
  return createMockFeed()
}
