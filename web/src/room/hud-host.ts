// The shell hosts the panels from web/src/hud on top of the room.
// Preferred: hud/index.ts exports mountHud(root, feed) and reads everything from the feed.
// Older panels that export renderHud(root, state) plus readHudState() still get drawn once.

export interface HudModule<F = unknown> {
  mountHud?: (root: HTMLElement, feed: F) => void
  renderHud?: (root: HTMLElement, state: unknown) => void
  readHudState?: () => unknown
}

export type HudMode = 'feed' | 'static' | 'none'

export function hostHud<F>(root: HTMLElement, feed: F, mod: HudModule<F>): HudMode {
  if (typeof mod.mountHud === 'function') {
    mod.mountHud(root, feed)
    return 'feed'
  }
  if (typeof mod.renderHud === 'function' && typeof mod.readHudState === 'function') {
    mod.renderHud(root, mod.readHudState())
    return 'static'
  }
  root.hidden = true
  return 'none'
}
