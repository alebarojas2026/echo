import './proof-layout.css'
export function fitProof(root: HTMLElement) {
  const footer = root.querySelector<HTMLElement>('footer')!
  const measure = () => {
    const height = footer.hidden ? 0 : Math.ceil(footer.getBoundingClientRect().height)
    root.style.setProperty('--proof-height', `${height}px`)
    root.toggleAttribute('data-proof-docked', height > 0)
  }
  const resize = new ResizeObserver(measure)
  resize.observe(footer)
  const visibility = new MutationObserver(measure)
  visibility.observe(footer, { attributes: true, attributeFilter: ['hidden'] })
  measure()
  return () => { resize.disconnect(); visibility.disconnect(); root.style.removeProperty('--proof-height'); root.removeAttribute('data-proof-docked') }
}
