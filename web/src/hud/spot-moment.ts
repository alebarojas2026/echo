import type {StateMsg} from '../room/contract'
import {hudLayout,type HudLayout} from './layout'
import {motionWord} from '../room/shown-alert'

/** The one-spot headline follows the board's classification, never a link threshold. */
export function spotMoment(state: StateMsg, layout: HudLayout = hudLayout): [string,string] | null {
 if(layout.zones.length!==1 || !state.pred || state.router!=='S-home' || state.armed&&state.tamper?.length)return null
 const pred=state.pred
 if(pred.present){
  if(pred.kind!=='person')return ['Presence uncertain','']
  const motion=motionWord(state,layout.presence?.line)
  return [motion==='moving'?'Someone is here, moving':motion==='still'?'Someone is here, standing still':'Someone is here','']
 }
 if(pred.kind!=='object')return null
 // The card under the headline carries the measured drop, so it is said once.
 return ['Something was left in the Wi-Fi line','']
}
