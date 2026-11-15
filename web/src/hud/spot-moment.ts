import type {StateMsg} from '../room/contract'
import {hudLayout,type HudLayout} from './layout'
import {wifiLinkId} from './dead-zone'
import {formatDrop} from './signal-trace'

/** The one-spot headline follows the board's classification, never a link threshold. */
export function spotMoment(state: StateMsg, layout: HudLayout = hudLayout): [string,string] | null {
 if(layout.zones.length!==1 || !state.pred || state.router!=='S-home' || state.armed&&state.tamper?.length)return null
 const pred=state.pred
 if(pred.present){
  if(pred.kind!=='person')return ['Presence uncertain','']
  return [pred.motion==='moving'?'Someone is here, moving':pred.motion==='still'?'Someone is here, standing still':'Someone is here','']
 }
 if(pred.kind!=='object')return null
 const link=state.links.find(row=>row.id===wifiLinkId(null,layout)&&row.status==='ok')
 const detail=typeof link?.drop_db==='number'&&Number.isFinite(link.drop_db)?formatDrop(link.drop_db):''
 return ['Something was left in the Wi-Fi line',detail]
}
