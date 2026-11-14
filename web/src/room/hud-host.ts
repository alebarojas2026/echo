import type { StateMsg } from './contract'
import type { Feed } from './feed'

// The shell hosts the panels from web/src/hud on top of the room. It understands, in order:
//   mountHud(root, feed)                      the panels read the feed themselves
//   renderHud(root, adaptHudState(state, proof))  the shell calls this on every new state, with /proof.json
//   renderHud(root, readHudState())           an older static preview, drawn once
// Errors inside the panels are not caught here; they reach the console.

export interface HudModule {
  mountHud?: (root: HTMLElement, feed: Feed) => void
  renderHud?: (root: HTMLElement, state: unknown) => void
  adaptHudState?: (state: StateMsg, proof: unknown) => unknown
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

export function hostHud(root: HTMLElement, feed: Feed, mod: HudModule, loadProof = fetchProof): HudMode {
  const { mountHud, renderHud, adaptHudState, readHudState } = mod
  if (typeof mountHud === 'function') {
    mountHud(root, feed)
    return 'feed'
  }
  if (typeof renderHud === 'function' && typeof adaptHudState === 'function') {
    let proof: unknown = null
    let drawn: StateMsg | null = null
    const draw = () => {
      const { state } = feed.current()
      if (state) renderHud(root, adaptHudState(state, proof))
      drawn = state
    }
    const refresh = () =>
      loadProof().then((p) => {
        proof = p
        draw()
      })
    void refresh()
    setInterval(refresh, PROOF_EVERY_MS)
    feed.subscribe(({ state }) => {
      if (state && state !== drawn) draw()
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
