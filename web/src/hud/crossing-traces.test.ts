import {expect,test} from 'vitest'
import gate from '../../tests/fixtures/gate-layout.json'
import desk from '../../tests/fixtures/desk-layout.json'
import {SignalHistory,signalSides,sideDrop,traceRuns} from './signal-trace'
import {wifiLinkId} from './dead-zone'
import {mockState} from './mock-layout'
test('every marked link has its own trace and Wi-Fi is boldest',()=>{
 const side=signalSides(gate)[0]
 expect(side.traces?.map(t=>t.id)).toEqual(gate.links.filter(l=>l.crosses_spot).map(l=>l.id))
 const wifi=gate.links.find(l=>l.crosses_spot&&l.kind==='wifi')!
 expect(side.primary).toBe(wifi.id)
 expect(wifiLinkId({...mockState('object',0,0).advice!,link:'pi5>unoq:wifi'},gate)).toBe(wifi.id)
 expect(side.traces!.find(t=>t.id===wifi.id)!.width).toBeGreaterThan(Math.max(...side.traces!.filter(t=>t.id!==wifi.id).map(t=>t.width)))
 expect(signalSides(desk).every(side=>!side.traces)).toBe(true)
})
test('a loud secondary link cannot replace the Wi-Fi number; missing readings break only their own trace',()=>{
 const history=new SignalHistory();history.refreshSides(gate)
 const side=history.sides[0],primary=side.primary!,secondary=side.links.find(id=>id!==primary)!
 const state=mockState('still',0,7000)
 const links=[{id:primary,dbm:-65,base_dbm:-50,drop_db:15,rate_hz:25,expected_hz:25,status:'ok',why:0},{id:secondary,dbm:-80,base_dbm:-50,drop_db:30,rate_hz:5,expected_hz:5,status:'ok',why:0}]
 expect(sideDrop(side,links)).toBe(15);expect(sideDrop(side,links.slice(1))).toBeNull()
 for(let i=0;i<5;i++)history.push({...state,seq:i,links:i===2?links.slice(1):links},i*100)
 expect(traceRuns(history.samples,0,550,primary)).toHaveLength(2)
 expect(traceRuns(history.samples,0,550,secondary)).toHaveLength(1)
 expect(history.samples[2].links?.[primary]).toBeNull()
})
