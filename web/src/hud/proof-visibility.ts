export const proofIds = ['presence-score', 'zone-score', 'person-object-score', 'train-seconds', 'ms-per-decision', 'watts', 'bytes-out', 'images-stored', 'models-count']

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

type Presence = { correct: number | null; total: number | null; always_empty_correct: number | null } | null | undefined

/** The Presence tile's words (#656): "19 of 20", and under it what a model that always says "nobody" would score
 *  on the same seconds. Counts as measured, never a percentage. Nothing measured: "__", and the tile is not drawn. */
export function presenceTile(presence: Presence) {
  const count = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) && value >= 0
  if (!presence || !count(presence.correct) || !count(presence.total) || !presence.total) return { score: '__', baseline: '' }
  return {
    score: `${presence.correct} of ${presence.total}`,
    baseline: count(presence.always_empty_correct) ? `always-empty would score ${presence.always_empty_correct} of ${presence.total}` : '',
  }
}
