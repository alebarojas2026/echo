import type { StateMsg } from './contract'
import type { Feed } from './feed'

// The shell hosts the panels from web/src/hud on top of the room. It understands, in order:
//   mountHud(root, feed)                      the panels read the feed themselves
//   renderHud(root, adaptHudState(state, proof, receivedAt, now))  on every new state and when the feed goes stale
//   renderHud(root, readHudState())           an older static preview, drawn once
// Errors inside the panels are not caught here; they reach the console.

export interface HudModule {
  mountHud?: (root: HTMLElement, feed: Feed) => void
  renderHud?: (root: HTMLElement, state: unknown) => void
  /** receivedAt and now share the feed's clock (performance.now()), so now - receivedAt is the feed's age. */
  adaptHudState?: (state: StateMsg, proof: unknown, receivedAt: number, now: number) => unknown
  readHudState?: () => unknown
}

export type HudMode = 'feed' | 'adapt' | 'static' | 'none'

const PROOF_EVERY_MS = 30_000

export async function fetchProof(url = '/proof.json'): Promise<unknown> {
  try {
    const res = await fetch(url, { headers: { accept: 'application/json' } })
    return res.ok ? await res.json() : null
  } catch {
    return null // no proof yet: the panels show "__"
  }
}

export function hostHud(root: HTMLElement, feed: Feed, mod: HudModule, loadProof = fetchProof, clock = () => performance.now()): HudMode {
  const { mountHud, renderHud, adaptHudState, readHudState } = mod
  if (typeof mountHud === 'function') {
    mountHud(root, feed)
    return 'feed'
  }
  if (typeof renderHud === 'function' && typeof adaptHudState === 'function') {
    let proof: unknown = null
    let drawn: StateMsg | null = null
    let drawnStale: boolean | null = null
    const draw = () => {
      const { state, receivedAt, stale } = feed.current()
      if (state) renderHud(root, adaptHudState(state, proof, receivedAt ?? clock(), clock()))
      drawn = state
      drawnStale = stale
    }
    const refresh = () =>
      loadProof().then((p) => {
        proof = p
        draw()
      })
    void refresh()
    setInterval(refresh, PROOF_EVERY_MS)
    // Redraw on every new state and when the feed goes stale or comes back (NO DATA).
    feed.subscribe(({ state, stale }) => {
      if (state && (state !== drawn || stale !== drawnStale)) draw()
    })
    return 'adapt'
  }
  if (typeof renderHud === 'function' && typeof readHudState === 'function') {
    renderHud(root, readHudState())
    return 'static'
  }
  if (Object.keys(mod).length) {
    console.warn('hud: web/src/hud/index.ts exports none of mountHud, renderHud + adaptHudState, renderHud + readHudState')
  }
  root.hidden = true
  return 'none'
}
