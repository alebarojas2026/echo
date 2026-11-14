// Text changes the way the screen does them (AGENTS.md Style): the old text fades out in 100 ms, the
// new text fades in over 140 ms, 40 ms later, in the same spot. Opacity and transform only.
// Nothing moves when the text is the same, and a ticking count (only its digits change) swaps in place.
const shown = new WeakMap()

export function quietChange(before, after) {
  return before === undefined || before.replace(/\d+/g, '#') === after.replace(/\d+/g, '#')
}

// swap(el, text): show text in el. render, if given, draws it (for text with coloured parts).
export function swap(el, text, render = () => { el.textContent = text }) {
  const before = shown.get(el)
  if (before === text) return
  shown.set(el, text)
  el.getAnimations().forEach((a) => a.cancel())
  if (quietChange(before, text) || matchMedia('(prefers-reduced-motion: reduce)').matches) return render()
  el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 100, fill: 'forwards' }).finished.then(() => {
    if (shown.get(el) !== text) return
    render()
    el.animate([{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 140, delay: 40, fill: 'both' })
  }, () => {})
}
