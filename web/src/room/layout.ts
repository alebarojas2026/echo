import { applyLayout } from './frame'

// Loads radio/nodes.json, which board/serve.py serves as /nodes.json (and vite.config.ts in development).
// If the file can't be had (missing, slow, offline), the room falls back to the nodes.json this page was built
// with ('contract'): the same layout the rest of the system runs on, not the old 2 m square that frame.ts starts
// as. If the file is there but the room does not understand it ('refused'), nothing is drawn from any other
// layout: the page says so in words (index.ts, refuseLayout). Drawing the layout the page was built with would
// put another kit on the screen, with devices that are not on the desk.

export type LayoutSource = 'nodes.json' | 'contract' | 'refused'

/** The layout the build carries (vite.config.ts), when there is one. */
function builtLayout(): unknown {
  return typeof __BUILD_LAYOUT__ === 'undefined' ? null : __BUILD_LAYOUT__
}

export async function loadLayout(url = '/nodes.json', timeoutMs = 2000, built: unknown = builtLayout()): Promise<LayoutSource> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: abort.signal, headers: { accept: 'application/json' } })
    if (res.ok) {
      let file: unknown
      try {
        file = await res.json()
      } catch (err) {
        if (abort.signal.aborted) throw err // too slow, not unreadable: the build's own
        return 'refused' // served, and not even JSON
      }
      return applyLayout(file) ? 'nodes.json' : 'refused'
    }
  } catch {
    // fall through to the build's own
  } finally {
    clearTimeout(timer)
  }
  if (built) applyLayout(built)
  return 'contract'
}
