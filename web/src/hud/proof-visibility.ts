export const proofIds = ['zone-score', 'person-object-score', 'train-seconds', 'ms-per-decision', 'watts', 'bytes-out', 'images-stored', 'models-count']

export function updateProofVisibility(root: HTMLElement) {
  let measured = false
  for (const id of proofIds) {
    const value = root.querySelector<HTMLElement>(`[data-testid="${id}"]`)
    if (!value) continue
    const visible = Number.isFinite(Number.parseFloat(value.textContent ?? ''))
    value.closest('div')!.hidden = !visible
    measured ||= visible
  }
  const block = root.querySelector<HTMLElement>('.hud-proof, footer')
  if (block) block.hidden = !measured
}
