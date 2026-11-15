import { blindSentence } from './health-words'
import { tamperWords } from './judge-tamper-panel'
import type { StateMsg } from '../room/contract'
import { hudLayout, zoneName, zonePlace } from './layout'
import { KIND_WORDS, type SecondKind } from './records'
export { zoneName } from './layout'
import { deadZone } from './dead-zone'
import { spotMoment } from './spot-moment'
import { shownAlert } from '../room/shown-alert'

export function judgeMoment(state: StateMsg | null, stale: boolean, layout = hudLayout) {
  // A replayed second with nothing to show says so. It is never drawn as an empty room.
  const replayed = (state as { replay?: { kind: SecondKind } } | null)?.replay?.kind
  if (replayed && replayed !== 'record') return KIND_WORDS[replayed]
  if (!state || stale) return ['No data', 'Last update more than 1 s ago']
  if (state.armed && state.tamper?.length) return [tamperWords(state, false), state.health.status === 'blind' ? 'Sensor blind' : '']
  if (state.health.status === 'blind') return ['Sensor blind', `${blindSentence(state, layout)}\nAlerts are paused`]
  // A dead zone is the moment while the board advises a move and measures it. An alert or an armed space comes first.
  const zone = shownAlert(state, layout.presence?.line)?.state === 'check_on' || state.armed ? null : deadZone(state, false)
  const spot = spotMoment(state, layout)
  if (spot) return spot
  if (zone) return [zone.headline, zone.detail]
  if (state.router !== 'S-home') return ['Paused', 'The router is off its home spot']
  const pred = state.pred
  if (!pred && layout.zones.length === 1 && !state.model?.trained) {
    // The one-spot layout needs no lesson: the Wi-Fi line decides once the empty space is measured. Never ask for training.
    const measured = state.links.some(link => link.drop_db != null)
    return measured ? ['One moment', 'Checking the radio line'] : ['Getting ready', 'Keep the spot clear while the empty space is measured']
  }
  if (!pred) return [state.model?.trained ? 'Recalibrating' : 'Not trained yet', 'Waiting for a room prediction']
  if (pred.kind === 'object' || (pred.kind !== 'person' && state.objects.length)) return ['An object, not a person', '']
  if (pred.kind === 'none' || pred.zone === 0) return ['Nobody is here', '']
  if (layout.zones.length > 1 && pred.zone_set.length > 1) return ['Between two zones', pred.zone_set.map(id => zoneName(id, layout)).join(' or ')]
  const place = zonePlace(pred.zone, layout)
  return [`${pred.motion === 'moving' ? 'Moving' : 'Still'} ${place}`, '']
}
