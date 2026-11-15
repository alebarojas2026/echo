import { feedSource, servedByBoard } from '../room/feed'
import { engineScene, MOCK_LAYOUT, sceneAt } from './mock'
import { parseLayout } from './model'
import { boardSource, mockSource } from './source'
import { mountEngine } from './view'

// The engine room's entry. Live on the board and in any built page; the simulated kit under the dev server, or
// when the address asks for it (?mock=running | silent | broken | answer | none). The same rule as the screen's.
const params = new URLSearchParams(location.search)
const host = document.getElementById('engine')!

if (feedSource(params, servedByBoard(), import.meta.env.PROD) === 'ws') {
  mountEngine(host, boardSource(params.get('ws') ?? `ws://${location.hostname || '127.0.0.1'}:8765/ws`))
} else {
  const scene = engineScene(params.get('mock'))
  // The simulated kit plays on the devices of the layout file in use, so its names are the real ones.
  const file = await fetch('/nodes.json', { headers: { accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  const layout = parseLayout(file) ?? parseLayout(typeof __BUILD_LAYOUT__ === 'undefined' ? null : __BUILD_LAYOUT__) ?? MOCK_LAYOUT
  // "none" plays a page with no board behind it, exactly as a live page shows it.
  mountEngine(host, mockSource((t) => sceneAt(scene, t, layout), scene === 'none' ? 'board' : 'mock'))
}
