import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Feed, FeedSnapshot } from './feed'
import { hostHud } from './hud-host'
import { mockState } from './mock'

function fakeFeed() {
  const listeners: ((s: FeedSnapshot) => void)[] = []
  let snap: FeedSnapshot = { state: null, receivedAt: null, stale: true, connected: true, source: 'mock' }
  const feed = {
    source: 'mock',
    current: () => snap,
    subscribe: (fn: (s: FeedSnapshot) => void) => {
      listeners.push(fn)
      fn(snap)
      return () => {}
    },
  } as unknown as Feed
  const push = (seq: number) => {
    snap = { ...snap, state: mockState('tour', seq, 0), stale: false }
    for (const fn of listeners) fn(snap)
  }
  return { feed, push }
}
const root = () => ({ hidden: false }) as HTMLElement

describe('hud host', () => {
  afterEach(() => vi.restoreAllMocks())

  it('hands the feed to panels that export mountHud', () => {
    const { feed } = fakeFeed()
    const mountHud = vi.fn()
    const el = root()
    expect(hostHud(el, feed, { mountHud, renderHud: vi.fn() })).toBe('feed')
    expect(mountHud).toHaveBeenCalledWith(el, feed)
  })

  it('renders adapted state on every new state, with the proof once it loads', async () => {
    const { feed, push } = fakeFeed()
    const renderHud = vi.fn()
    const adaptHudState = vi.fn((state: { seq: number }, proof: unknown) => ({ seq: state.seq, proof }))
    const proof = { train_s: null }
    expect(hostHud(root(), feed, { renderHud, adaptHudState }, async () => proof)).toBe('adapt')
    push(1)
    expect(renderHud.mock.calls.at(-1)![1]).toEqual({ seq: 1, proof: null })
    await Promise.resolve()
    await Promise.resolve()
    push(2)
    expect(renderHud.mock.calls.at(-1)![1]).toEqual({ seq: 2, proof })
  })

  it('draws older static panels once', () => {
    const { feed } = fakeFeed()
    const renderHud = vi.fn()
    expect(hostHud(root(), feed, { renderHud, readHudState: () => ({ ok: 1 }) })).toBe('static')
    expect(renderHud.mock.calls[0][1]).toEqual({ ok: 1 })
  })

  it('hides the layer with no panels, and says so when the panels export nothing it knows', () => {
    const { feed } = fakeFeed()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const el = root()
    expect(hostHud(el, feed, {})).toBe('none')
    expect(el.hidden).toBe(true)
    expect(warn).not.toHaveBeenCalled()
    expect(hostHud(root(), feed, { renderHud: vi.fn() })).toBe('none')
    expect(warn).toHaveBeenCalledOnce()
  })
})
