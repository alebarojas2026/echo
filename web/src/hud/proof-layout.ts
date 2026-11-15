import './proof-layout.css'
export function fitProof(root: HTMLElement) {
  const footer = root.querySelector<HTMLElement>('footer')!
  const measure = () => {
    const height = footer.hidden ? 0 : Math.ceil(footer.getBoundingClientRect().height)
    root.style.setProperty('--proof-height', `${height}px`)
    root.toggleAttribute('data-proof-docked', height > 0)
    // The room ends where the docked bar begins, so the bar never lies over its legend or its floor.
    document.documentElement.style.setProperty('--hud-proof-height', `${height}px`)
  }
  const resize = new ResizeObserver(measure)
  resize.observe(footer)
  const visibility = new MutationObserver(measure)
  visibility.observe(footer, { attributes: true, attributeFilter: ['hidden'] })
  measure()
  return () => { resize.disconnect(); visibility.disconnect(); root.style.removeProperty('--proof-height'); root.removeAttribute('data-proof-docked'); document.documentElement.style.removeProperty('--hud-proof-height') }
}
