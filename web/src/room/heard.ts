import type { LinkState } from './contract'
import { parseLinkId } from './frame'
import { Held } from './motion'

// Devices are live, like the person: the room draws a device only while the board is actually hearing it, never
// because nodes.json lists it. A device is heard while any link it sends or receives has readings (rate_hz > 0,
// readings in the last 2 s). It shows once that has held 300 ms, and lets go after 2.5 s of silence, so one
// missed reading never makes it blink.

/** heard: drawn in full. lost: heard before, quiet now: drawn faint with "not heard". never: not drawn. */
export type Hearing = 'heard' | 'lost' | 'never'

const ON_MS = 300
const OFF_MS = 2500

/** The nodes with at least one link that has readings right now. */
export function heardNow(links: readonly LinkState[]): Set<string> {
  const out = new Set<string>()
  for (const l of links) {
    if (!((l.rate_hz ?? 0) > 0)) continue
    const p = parseLinkId(l.id)
    if (!p) continue
    out.add(p.tx)
    out.add(p.rx)
  }
  return out
}

export class HeardNodes {
  private readonly held = new Map<string, Held<boolean>>()
  private readonly ever = new Set<string>()

  /** Each node's hearing after this state's links, held so it never flickers. */
  update(ids: readonly string[], links: readonly LinkState[], nowMs: number): Map<string, Hearing> {
    const now = heardNow(links)
    const out = new Map<string, Hearing>()
    for (const id of ids) {
      let h = this.held.get(id)
      if (!h) this.held.set(id, (h = new Held<boolean>(false, (on) => (on ? ON_MS : OFF_MS))))
      const heard = h.update(now.has(id), nowMs)
      if (heard) this.ever.add(id)
      out.set(id, heard ? 'heard' : this.ever.has(id) ? 'lost' : 'never')
    }
    return out
  }
}
