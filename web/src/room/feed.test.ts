import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CmdMsg } from './contract'
import { feedFrom, wsTransport, type Transport } from './feed'
import { mockState } from './mock'

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
