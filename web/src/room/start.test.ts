import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Feed } from './feed'
import { mountRoom, NO_3D_WORDS } from './index'

/** Just enough of an element for the room's start: it keeps what is appended and the words set on it. */
function el(tag: string): Record<string, unknown> & { children: ReturnType<typeof el>[] } {
  const classes = new Set<string>()
  const node = {
    tag,
    children: [] as ReturnType<typeof el>[],
    dataset: {} as Record<string, string>,
    style: {},
    hidden: false,
    textContent: '',
    className: '',
    classList: { add: (c: string) => void classes.add(c), toggle: () => false, contains: (c: string) => classes.has(c) },
    setAttribute: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    append: (...kids: ReturnType<typeof el>[]) => void node.children.push(...kids),
    // The browser has no 3D to give: every kind of context comes back null.
    getContext: () => null,
  }
  return node
}

describe('a 3D view that cannot start', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says so in the room in words and leaves the rest of the page alone', () => {
    vi.stubGlobal('document', { createElement: el, createElementNS: (_ns: string, tag: string) => el(tag), body: el('body') })
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    const host = el('main')
    const feed = { source: 'ws', subscribe: () => () => {}, onEvent: () => () => {} } as unknown as Feed
    expect(mountRoom(host as unknown as HTMLElement, feed, new URLSearchParams())).toBeNull()
    expect(quiet).toHaveBeenCalled() // the reason still reaches the console
    quiet.mockRestore()
    expect(host.dataset).toMatchObject({ room3d: 'unavailable' })
    const notice = host.children.find((c) => c.className === 'room-notice')!
    expect(notice.hidden).toBe(false)
    expect(notice.children.map((c) => c.textContent)).toEqual(['3D view unavailable', 'The radio keeps working.'])
    expect([...NO_3D_WORDS]).toEqual(['3D view unavailable', 'The radio keeps working.'])
    expect(host.children.some((c) => c.tag === 'canvas')).toBe(false) // no dead canvas left in the room
  })
})
