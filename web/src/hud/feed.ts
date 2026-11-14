import { mountHudControls, type HudCommand } from './controls'
import { fetchProof } from '../room/hud-host'
import { adaptHudState, type Proof, type ScreenState } from './state'

export interface HudFeed {
  send(cmd: HudCommand['cmd'], args: Record<string, string>): void
  subscribe(listener: (snapshot: { state: ScreenState | null; stale: boolean }) => void): () => void
}

export function connectHud(
  root: HTMLElement,
  feed: HudFeed | null,
  render: (root: HTMLElement, state: ReturnType<typeof adaptHudState>) => void,
) {
  const panels = document.createElement('div')
  const controls = document.createElement('details')
  controls.className = 'hud-shell-controls'
  const summary = document.createElement('summary')
  summary.textContent = 'Controls'
  const content = document.createElement('div')
  controls.append(summary, content)
  mountHudControls(content, ({ cmd, args }) => feed?.send(cmd, args))
  root.replaceChildren(panels, controls)
  root.classList.add('hud-shell-panels')

  let proof: Proof | null = null
  let latest: ScreenState | null = null
  let stale = true
  let disposed = false
  const update = () => render(panels, adaptHudState(latest, proof, stale ? 0 : 1, stale ? 1001 : 1))
  const unsubscribe = feed?.subscribe(snapshot => {
    latest = snapshot.state
    stale = snapshot.stale
    update()
  })
  if (!feed) update()
  const refresh = () => fetchProof().then(value => {
    if (disposed) return
    proof = value as Proof | null
    update()
  })
  void refresh()
  const timer = setInterval(refresh, 30_000)
  return () => {
    clearInterval(timer)
    disposed = true
    unsubscribe?.()
  }
}


