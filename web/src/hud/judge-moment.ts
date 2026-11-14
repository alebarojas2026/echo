import type { StateMsg } from '../room/contract'
import { ZONES } from '../room/frame'

const places: Record<string, string> = { Bed: 'by the bed', Chair: 'at the chair', Hall: 'in the hall', Bathroom: 'in the bathroom' }
export function zoneName(zone: number | null | undefined) {
  return ZONES.find(item => item.id === zone)?.name ?? 'the room'
}
export function judgeMoment(state: StateMsg | null, stale: boolean) {
  if (!state || stale) return ['No data', 'Last update more than 1 s ago']
  if (state.health.status === 'blind') return ['Sensor blind', 'A radio link stopped. Alerts are paused']
  if (state.router !== 'S-home') return ['Paused', 'The router is off its home spot']
  const pred = state.pred
  if (!pred) return [state.model?.trained ? 'Recalibrating' : 'Not trained yet', 'Waiting for a room prediction']
  if (pred.kind === 'object' || (pred.kind !== 'person' && state.objects.length)) return ['An object, not a person', '']
  if (pred.kind === 'none' || pred.zone === 0) return ['Nobody is here', '']
  if (pred.zone_set.length > 1) return ['Between two zones', pred.zone_set.map(zoneName).join(' or ')]
  const place = places[zoneName(pred.zone)] ?? 'in the room'
  return [`${pred.motion === 'moving' ? 'Moving' : 'Still'} ${place}`, '']
}
