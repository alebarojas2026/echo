import type { CmdMsg, CmdName, EventMsg, StateMsg } from './contract'
import { createMockSource, mockScenario } from './mock'

// The one place screen data comes from. The room and the hud panels both read it.
//   live   the brain's WebSocket, ws://<this host>:8765/ws (?ws=<url> overrides)
//   mock   mock states; ?mock=<scenario> picks one (see mock.ts)
// Which one (feedSource): a page the board serves, and any built page, is live unless the address asks for the
// mock in so many words (?mock=... or ?src=mock), so a bookmark, a restart or a typed address at the desk can
// never show a judge a simulated person. Only the dev server (`vite`) plays the mock by default. ?src=ws is live
// anywhere. Live with no state yet shows NO DATA, never the tour.

export type FeedSource = 'mock' | 'ws'

export interface FeedSnapshot {
  state: StateMsg | null
  /** performance.now() when the last state arrived, or null before the first one. */
  receivedAt: number | null
  /** No state for more than STALE_MS: the screen shows NO DATA (grey). */
  stale: boolean
  /** The WebSocket is open (always true for the mock). */
  connected: boolean
  source: FeedSource
}

export interface Feed {
  readonly source: FeedSource
  current(): FeedSnapshot
  /** Called now and on every new state or change of stale/connected. Returns an unsubscribe function. */
  subscribe(fn: (snap: FeedSnapshot) => void): () => void
  /** Called for every event message (contract section 5). */
  onEvent(fn: (event: EventMsg) => void): () => void
  send(cmd: CmdName, args?: Record<string, unknown>): void
}

export const STALE_MS = 1000

/** Something that delivers parsed messages and accepts commands: the WebSocket or the mock. */
export interface Transport {
  start(deliver: (msg: unknown) => void, setConnected: (up: boolean) => void): void
  send(msg: CmdMsg): void
}

/** Live or mock for this address. `onBoard`: the board served the page (servedByBoard). `built`: a production
 *  build, not the dev server. */
export function feedSource(params: URLSearchParams, onBoard: boolean, built: boolean): FeedSource {
  if (params.has('mock') || params.get('src') === 'mock') return 'mock'
  return params.get('src') === 'ws' || onBoard || built ? 'ws' : 'mock'
}

/** board/serve.py marks the page it serves with <meta name="radio-sight-board" content="live"> (#642). */
export function servedByBoard(doc: Pick<Document, 'querySelector'> = document): boolean {
  return doc.querySelector('meta[name="radio-sight-board"]')?.getAttribute('content') === 'live'
}

export function createFeed(params = new URLSearchParams(location.search)): Feed {
  if (feedSource(params, servedByBoard(), import.meta.env.PROD) === 'ws') {
    const url = params.get('ws') ?? `ws://${location.hostname || '127.0.0.1'}:8765/ws`
    return feedFrom('ws', wsTransport(url))
  }
  return feedFrom('mock', createMockSource(mockScenario(params.get('mock'))))
}

export function feedFrom(source: FeedSource, transport: Transport, now = () => performance.now()): Feed {
  const listeners = new Set<(snap: FeedSnapshot) => void>()
  const eventListeners = new Set<(event: EventMsg) => void>()
  let snap: FeedSnapshot = { state: null, receivedAt: null, stale: true, connected: false, source }

  const publish = (next: Partial<FeedSnapshot>) => {
    snap = { ...snap, ...next }
    for (const fn of listeners) isolated(fn, snap)
  }

  transport.start(
    (msg) => {
      if (!isMsg(msg)) return
      if (msg.type === 'state') publish({ state: msg as StateMsg, receivedAt: now(), stale: false })
      else if (msg.type === 'event') for (const fn of eventListeners) isolated(fn, msg as EventMsg)
    },
    (up) => {
      if (up !== snap.connected) publish({ connected: up })
    },
  )

  setInterval(() => {
    const stale = snap.receivedAt === null || now() - snap.receivedAt > STALE_MS
    if (stale !== snap.stale) publish({ stale })
  }, 100)

  return {
    source,
    current: () => snap,
    subscribe(fn) {
      listeners.add(fn)
      fn(snap)
      return () => listeners.delete(fn)
    },
    onEvent(fn) {
      eventListeners.add(fn)
      return () => eventListeners.delete(fn)
    },
    send(cmd, args = {}) {
      transport.send({ v: 2, type: 'cmd', cmd, args })
    },
  }
}

/** Calls one subscriber. If it throws, the error is rethrown on its own so it shows in the console
 *  without stopping the room or the other subscribers from getting this message. */
function isolated<T>(fn: (value: T) => void, value: T) {
  try {
    fn(value)
  } catch (err) {
    setTimeout(() => {
      throw err
    })
  }
}

function isMsg(msg: unknown): msg is { v: number; type: string } {
  return typeof msg === 'object' && msg !== null && (msg as { v?: unknown }).v === 2
}

/** An open socket that has delivered nothing for this long is taken for dead and replaced. The brain sends about
 *  ten states a second whatever is happening, so three silent seconds are not a quiet room. */
export const SILENT_MS = 3000

/**
 * The brain's WebSocket. Reconnects with a growing pause (0.5 s up to 5 s) and never throws.
 * A connection can die without closing (the laptop roams, the Pi's forwarding restarts, the board's service is
 * restarted under it): the browser then keeps the dead socket open for minutes and the screen sits on "No data"
 * until someone reloads it. So a socket that is open and silent for SILENT_MS is dropped here and the same
 * reconnect runs, pause and all, so a board that is really down is not hammered.
 */
export function wsTransport(url: string): Transport {
  let socket: WebSocket | null = null
  return {
    start(deliver, setConnected) {
      let pause = 500
      const open = () => {
        const ws = new WebSocket(url)
        socket = ws
        let watch: ReturnType<typeof setTimeout> | undefined
        const closed = () => {
          clearTimeout(watch)
          if (socket !== ws) return // already replaced
          setConnected(false)
          socket = null
          setTimeout(open, pause)
          pause = Math.min(5000, pause * 2)
        }
        /** (Re)starts the silence watch: called when the socket opens and on every message. */
        const heard = () => {
          clearTimeout(watch)
          watch = setTimeout(() => {
            // Not waiting for the close handshake: on a dead connection it may never finish.
            ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null
            try {
              ws.close()
            } catch {
              // a socket that can't even be closed is gone already
            }
            closed()
          }, SILENT_MS)
        }
        ws.onopen = () => {
          pause = 500
          setConnected(true)
          heard()
        }
        ws.onmessage = (e) => {
          heard()
          let msg: unknown
          try {
            msg = JSON.parse(String(e.data))
          } catch {
            return // a message that isn't JSON is dropped; the next state replaces it anyway
          }
          deliver(msg) // outside the try: an error in a subscriber must reach the console
        }
        ws.onclose = closed
        ws.onerror = () => ws.close()
      }
      open()
    },
    send(msg) {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg))
    },
  }
}
