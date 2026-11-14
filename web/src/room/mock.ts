import type { StateMsg } from './contract'
import { LINK_IDS } from './frame'

// A plausible state message (CONTRACTS.md v2 section 5) for working on the screen without the board.
// Every number here is mock data for layout only; src is "sim" so the screen never presents it as live.
export function mockState(seq: number, now = Date.now()): StateMsg {
  return {
    v: 2,
    type: 'state',
    t: now,
    seq,
    src: 'sim',
    cam: 'off',
    router: 'S-home',
    links: LINK_IDS.map((id) => ({
      id,
      dbm: -60,
      base_dbm: -60,
      drop_db: 0,
      rate_hz: 9.5,
      expected_hz: 9.5,
      status: 'ok',
      why: 0,
    })),
    health: { status: 'ok', blind: [], reason: null },
    pred: null,
    objects: [],
    xray: null,
    alert: { state: 'none', zone: null, still_s: null, limit_s: null },
    checkin: null,
    advice: null,
    narration: null,
    teacher: null,
    model: null,
    board: null,
  }
}
