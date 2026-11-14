import { applyLayout } from './frame'

// Loads radio/nodes.json, which board/serve.py serves as /nodes.json (and vite.config.ts in development).
// Falls back to the contract's layout, already in frame.ts, if the file is missing, slow or malformed.

export type LayoutSource = 'nodes.json' | 'contract'

export async function loadLayout(url = '/nodes.json', timeoutMs = 2000): Promise<LayoutSource> {
  const abort = new AbortController()
  const timer = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const res = await fetch(url, { signal: abort.signal, headers: { accept: 'application/json' } })
    if (!res.ok) return 'contract'
    return applyLayout(await res.json()) ? 'nodes.json' : 'contract'
  } catch {
    return 'contract'
  } finally {
    clearTimeout(timer)
  }
}
