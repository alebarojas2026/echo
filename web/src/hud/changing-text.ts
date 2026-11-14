export function changingText(element: HTMLElement) {
  let requested = ''
  let generation = 0
  const cancel = () => element.getAnimations().forEach(animation => animation.cancel())
  return {
    set(value: string) {
      if (requested === value) return
      requested = value
      const current = ++generation
      cancel()
      if (!element.textContent || matchMedia('(prefers-reduced-motion: reduce)').matches) {
        element.textContent = value
        return
      }
      const out = element.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, fill: 'forwards' })
      void out.finished.then(() => {
        if (current !== generation) return
        element.textContent = value
        const incoming = element.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 140, delay: 40, fill: 'both' })
        void incoming.finished.then(() => { if (current === generation) cancel() }).catch(() => {})
      }).catch(() => {})
    },
    dispose() { generation++; cancel() },
  }
}
