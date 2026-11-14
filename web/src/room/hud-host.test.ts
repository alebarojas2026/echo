import { describe, expect, it, vi } from 'vitest'
import type { Feed } from './feed'
import { hostHud } from './hud-host'

const feed = { source: 'mock' } as Feed
const root = () => ({ hidden: false }) as HTMLElement

describe('hud host', () => {
  it('hands the feed to panels that export mountHud', () => {
    const mountHud = vi.fn()
    const el = root()
    expect(hostHud(el, feed, { mountHud, renderHud: vi.fn() })).toBe('feed')
    expect(mountHud).toHaveBeenCalledWith(el, feed)
  })

  it('draws older panels once from their own state', () => {
    const renderHud = vi.fn()
    expect(hostHud(root(), feed, { renderHud, readHudState: () => ({ ok: 1 }) })).toBe('static')
    expect(renderHud.mock.calls[0][1]).toEqual({ ok: 1 })
  })

  it('hides the layer when there are no panels', () => {
    const el = root()
    expect(hostHud(el, feed, {})).toBe('none')
    expect(el.hidden).toBe(true)
  })
})
