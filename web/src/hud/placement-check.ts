import type { LinkState, StateMsg } from '../room/contract'

const CAPTURE_MS = 5000
const MIN_SAMPLES = 10
interface Quiet { base: number; n: number; mean: number; m2: number; peak: number; first: number; last: number }
export const measured = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
export function usable(link: LinkState) {
  return link.status === 'ok' && measured(link.rate_hz) && link.rate_hz > 0 && measured(link.base_dbm) && measured(link.drop_db)
}

export class PlacementCheck {
  private quiet = new Map<string, Quiet>()
  private start: number | null = null
  private last = -Infinity
  private layout = ''
  capturing = false
  elapsed = 0
  reset() { this.quiet.clear(); this.start = null; this.last = -Infinity; this.capturing = false; this.elapsed = 0 }
  begin() { this.reset(); this.capturing = true }
  update(state: StateMsg | null, stale: boolean, layoutKey = '') {
    if (layoutKey !== this.layout) { this.reset(); this.layout = layoutKey }
    if (!state || stale || state.src === 'replay' || !measured(state.t)) return
    if (state.t < this.last) this.reset()
    for (const [id, quiet] of this.quiet) {
      if (state.links.find(link => link.id === id)?.base_dbm !== quiet.base) this.quiet.delete(id)
    }
    if (state.t === this.last) return
    this.last = state.t
    if (!this.capturing) return
    this.start ??= state.t
    this.elapsed = Math.min(CAPTURE_MS, state.t - this.start)
    if (state.t - this.start > CAPTURE_MS + 1000) { this.reset(); return }
    for (const link of state.links) {
      if (!usable(link)) continue
      let quiet = this.quiet.get(link.id)
      if (!quiet) {
        quiet = { base: link.base_dbm!, n: 0, mean: 0, m2: 0, peak: -Infinity, first: state.t, last: state.t }
        this.quiet.set(link.id, quiet)
      }
      const drop = link.drop_db!
      quiet.n++
      const delta = drop - quiet.mean
      quiet.mean += delta / quiet.n
      quiet.m2 += delta * (drop - quiet.mean)
      quiet.peak = Math.max(quiet.peak, drop)
      quiet.last = state.t
    }
    if (this.elapsed >= CAPTURE_MS) this.capturing = false
  }
  threshold(link: LinkState): number | null {
    const quiet = this.quiet.get(link.id)
    if (this.capturing || !quiet || quiet.base !== link.base_dbm || quiet.n < MIN_SAMPLES || quiet.last - quiet.first < CAPTURE_MS - 500) return null
    return Math.max(0, quiet.peak, quiet.mean + 3 * Math.sqrt(quiet.m2 / (quiet.n - 1)))
  }
  seen(link: LinkState, stale: boolean) {
    const threshold = this.threshold(link)
    return !stale && usable(link) && threshold !== null && link.drop_db! > threshold
  }
}
