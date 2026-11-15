import { mockState as roomMock, type MockScenario } from '../room/mock'
import type { StateMsg } from '../room/contract'
import { hudLayout, type HudLayout } from './layout'

export function alignMockState(state: StateMsg | null, layout: HudLayout = hudLayout): StateMsg | null {
  if (!state) return null
  const zone = (id: number) => id === 0 ? 0 : layout.zones[(id - 1) % layout.zones.length]?.id ?? 0
  const pred = state.pred && { ...state.pred, zone: zone(state.pred.zone), zone_set: [...new Set(state.pred.zone_set.map(zone))] }
  if (pred) pred.probs = Array.from({ length: layout.zones.length + 1 }, (_, i) => i === pred.zone ? 1 : 0)
  const alertZone = state.alert?.zone == null ? null : zone(state.alert.zone)
  return { ...state, pred,
    teacher: state.teacher && { ...state.teacher, zone: zone(state.teacher.zone) },
    alert: state.alert && { ...state.alert, zone: alertZone, limit_s: layout.zones.find(z => z.id === alertZone)?.still_alert_s ?? null },
  }
}
export function mockState(scenario: MockScenario, seq: number, elapsed: number) {
  return alignMockState(roomMock(scenario, seq, elapsed))!
}
