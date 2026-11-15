import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CmdMsg } from './contract'
import { feedFrom, feedSource, servedByBoard, SILENT_MS, wsTransport, type Transport } from './feed'
import { mockScenario, mockState } from './mock'

function fakeTransport() {
  const sent: CmdMsg[] = []
  let deliver: (msg: unknown) => void = () => {}
  let connect: (up: boolean) => void = () => {}
  const transport: Transport = {
    start(d, c) {
      deliver = d
      connect = c
    },
    send: (msg) => sent.push(msg),
  }
  return { transport, sent, deliver: (m: unknown) => deliver(m), connect: (up: boolean) => connect(up) }
}

describe('feed', () => {
  let clock = 0
  beforeEach(() => {
    vi.useFakeTimers()
    clock = 0
  })
  afterEach(() => vi.useRealTimers())

  it('is stale until the first state, then goes stale again after 1 s without one', () => {
    const t = fakeTransport()
    const feed = feedFrom('ws', t.transport, () => clock)
    expect(feed.current().stale).toBe(true)

    t.deliver(mockState('tour', 1, 0))
    expect(feed.current().stale).toBe(false)
    expect(feed.current().state?.seq).toBe(1)

    clock = 900
    vi.advanceTimersByTime(900)
    expect(feed.current().stale).toBe(false)
    clock = 1100
    vi.advanceTimersByTime(200)
    expect(feed.current().stale).toBe(true)
  })

  it('ignores messages that are not contract v2 and routes events', () => {
    const t = fakeTransport()
    const feed = feedFrom('ws', t.transport, () => clock)
    const events = vi.fn()
    feed.onEvent(events)
    t.deliver({ v: 1, type: 'state' })
    t.deliver('garbage')
    expect(feed.current().state).toBeNull()
    t.deliver({ v: 2, type: 'event', t: 0, seq: 1, src: 'sim', id: 'e1', kind: 'enter', info: { zone: 2 } })
    expect(events).toHaveBeenCalledOnce()
  })

  it('tells subscribers about connection changes and wraps commands', () => {
    const t = fakeTransport()
    const feed = feedFrom('ws', t.transport, () => clock)
    const seen = vi.fn()
    feed.subscribe(seen)
    t.connect(true)
    expect(seen.mock.calls.at(-1)![0].connected).toBe(true)
    feed.send('router_moved', { spot: 'S-W30' })
    expect(t.sent).toEqual([{ v: 2, type: 'cmd', cmd: 'router_moved', args: { spot: 'S-W30' } }])
  })
})

describe('websocket transport', () => {
  it('drops bad JSON but lets a subscriber error reach the console', () => {
    let sock: { onmessage?: (e: { data: string }) => void } = {}
    vi.stubGlobal(
      'WebSocket',
      class {
        static OPEN = 1
        constructor() {
          sock = this
        }
      },
    )
    const deliver = vi.fn((msg: unknown) => {
      if ((msg as { boom?: boolean }).boom) throw new Error('subscriber failed')
    })
    wsTransport('ws://test/ws').start(deliver, () => {})
    expect(() => sock.onmessage!({ data: 'not json' })).not.toThrow()
    expect(deliver).not.toHaveBeenCalled()
    expect(() => sock.onmessage!({ data: '{"boom":true}' })).toThrow('subscriber failed')
    vi.unstubAllGlobals()
  })
})

describe('a connection that dies without closing', () => {
  interface Sock {
    onopen: (() => void) | null
    onmessage: ((e: { data: string }) => void) | null
    onclose: (() => void) | null
    closed: boolean
  }
  let socks: Sock[] = []
  beforeEach(() => {
    vi.useFakeTimers()
    socks = []
    vi.stubGlobal(
      'WebSocket',
      class {
        static OPEN = 1
        onopen = null
        onmessage = null
        onclose = null
        closed = false
        constructor() {
          socks.push(this as unknown as Sock)
        }
        close() {
          this.closed = true // a dead connection: the close handshake never finishes, so onclose never comes
        }
      },
    )
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
  const state = (seq: number) => ({ data: JSON.stringify(mockState('empty', seq, 0)) })

  it('opens a new socket after 3 s of silence, and its states clear "No data"', () => {
    let clock = 0
    const feed = feedFrom('ws', wsTransport('ws://test/ws'), () => clock)
    const tick = (ms: number) => {
      clock += ms
      vi.advanceTimersByTime(ms)
    }
    socks[0].onopen!()
    for (let seq = 1; seq <= 5; seq++) {
      socks[0].onmessage!(state(seq))
      tick(100)
    }
    expect(feed.current()).toMatchObject({ stale: false, connected: true })
    // The connection dies: nothing more arrives, and nothing says it closed.
    tick(1500)
    expect(feed.current()).toMatchObject({ stale: true, connected: true }) // "No data", on a socket that looks open
    expect(socks).toHaveLength(1)
    tick(SILENT_MS - 1500)
    expect(socks[0].closed).toBe(true)
    expect(feed.current().connected).toBe(false)
    expect(socks).toHaveLength(1) // the usual pause first
    tick(500)
    expect(socks).toHaveLength(2)
    socks[1].onopen!()
    socks[1].onmessage!(state(6))
    expect(feed.current()).toMatchObject({ stale: false, connected: true })
    expect(feed.current().state!.seq).toBe(6)
    // A late word from the dead socket changes nothing: it has no handlers left.
    expect(socks[0].onmessage).toBeNull()
    expect(socks[0].onclose).toBeNull()
  })

  it('leaves a talking socket alone, and does not hammer a board that stays silent', () => {
    wsTransport('ws://test/ws').start(() => {}, () => {})
    socks[0].onopen!()
    for (let t = 0; t < 20_000; t += 500) {
      socks[0].onmessage!(state(t))
      vi.advanceTimersByTime(500) // two states a second, as slow as a real Bluetooth link's readings
    }
    expect(socks).toHaveLength(1)
    // Now a board that accepts the connection and says nothing: one new socket per silence plus pause, no faster.
    vi.advanceTimersByTime(SILENT_MS + 500)
    expect(socks).toHaveLength(2)
    for (let i = 0; i < 5; i++) {
      socks.at(-1)!.onopen!()
      vi.advanceTimersByTime(SILENT_MS + 500)
    }
    expect(socks).toHaveLength(7)
    // And one that closes properly reconnects as before, once.
    socks.at(-1)!.onclose!()
    vi.advanceTimersByTime(10_000)
    expect(socks).toHaveLength(8)
  })
})

describe('live or mock (#642)', () => {
  const q = (query: string) => new URLSearchParams(query)
  const page = (meta: string | null) => ({
    querySelector: (sel: string) => (sel === 'meta[name="radio-sight-board"]' && meta !== null ? ({ getAttribute: () => meta } as unknown as Element) : null),
  })

  it('reads the mark the board puts on the page it serves', () => {
    expect(servedByBoard(page('live'))).toBe(true)
    expect(servedByBoard(page(null))).toBe(false)
    expect(servedByBoard(page('preview'))).toBe(false)
  })

  it('is live on the board with no query, a bookmark or a restart: never the tour', () => {
    expect(feedSource(q(''), true, true)).toBe('ws')
    expect(feedSource(q('q=hi&view=hall'), true, true)).toBe('ws')
    expect(feedSource(q('src=ws'), true, true)).toBe('ws')
  })

  it('plays the mock on the board only when the address asks for it in so many words', () => {
    expect(feedSource(q('mock=1'), true, true)).toBe('mock')
    expect(feedSource(q('mock=still'), true, true)).toBe('mock')
    expect(feedSource(q('src=mock'), true, true)).toBe('mock')
  })

  it('is live for any built page, and the mock by default only under the dev server', () => {
    expect(feedSource(q(''), false, true)).toBe('ws')
    expect(feedSource(q(''), false, false)).toBe('mock')
    expect(feedSource(q('src=ws'), false, false)).toBe('ws')
  })

  it('plays the tour for ?mock=1 or an unknown name, and the named scenario otherwise', () => {
    expect(mockScenario('1')).toBe('tour')
    expect(mockScenario('')).toBe('tour')
    expect(mockScenario(null)).toBe('tour')
    expect(mockScenario('still')).toBe('still')
  })
})
