import type { StateMsg } from '../room/contract'
import { hudLayout, zoneName, zonePlace } from './layout'
export { zoneName } from './layout'

export function judgeMoment(state: StateMsg | null, stale: boolean, layout = hudLayout) {
  if (!state || stale) return ['No data', 'Last update more than 1 s ago']
  if (state.health.status === 'blind') return ['Sensor blind', 'A radio link stopped. Alerts are paused']
  if (state.router !== 'S-home') return ['Paused', 'The router is off its home spot']
  const pred = state.pred
  if (!pred) return [state.model?.trained ? 'Recalibrating' : 'Not trained yet', 'Waiting for a room prediction']
  if (pred.kind === 'object' || (pred.kind !== 'person' && state.objects.length)) return ['An object, not a person', '']
  if (pred.kind === 'none' || pred.zone === 0) return ['Nobody is here', '']
  if (pred.zone_set.length > 1) return ['Between two zones', pred.zone_set.map(id => zoneName(id, layout)).join(' or ')]
  const place = zonePlace(pred.zone, layout)
  return [`${pred.motion === 'moving' ? 'Moving' : 'Still'} ${place}`, '']
}
