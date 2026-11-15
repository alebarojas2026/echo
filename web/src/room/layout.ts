import { applyLayout } from './frame'

// Loads radio/nodes.json, which board/serve.py serves as /nodes.json (and vite.config.ts in development).
// If the file is missing, slow or malformed, the room falls back to the nodes.json this page was built with
// ('contract'): the same layout the rest of the system runs on, not the old 2 m square that frame.ts starts as.

export type LayoutSource = 'nodes.json' | 'contract'

/** The layout the build carries (vite.config.ts), when there is one. */
function builtLayout(): unknown {
  return typeof __BUILD_LAYOUT__ === 'undefined' ? null : __BUILD_LAYOUT__
}

export async function loadLayout(url = '/nodes.json', timeoutMs = 2000, built: unknown = builtLayout()): Promise<LayoutSource> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: abort.signal, headers: { accept: 'application/json' } })
    if (res.ok && applyLayout(await res.json())) return 'nodes.json'
  } catch {
    // fall through to the build's own
  } finally {
    clearTimeout(timer)
  }
  if (built) applyLayout(built)
  return 'contract'
}
