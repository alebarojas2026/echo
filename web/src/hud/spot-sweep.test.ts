import {expect,test} from 'vitest'
import gate from '../../tests/fixtures/gate-layout.json'
import desk from '../../tests/fixtures/desk-layout.json'
import {moveWords,wifiLinkId} from './dead-zone'
import {signalSides} from './signal-trace'
import {judgeMoment} from './judge-moment'
import {mockState} from './mock-layout'
const layout={...gate,links:gate.links.map(link=>({...link,crosses_spot:link.id==='pi5>pi5b:wifi'||link.crosses_spot}))}
test('the one spot includes every marked radio kind and selects its crossing Wi-Fi link',()=>{
 expect(signalSides(layout)[0].links).toContain('pi5>pi5b:wifi')
 expect(wifiLinkId(null,layout)).toBe('pi5>pi5b:wifi')
 expect(wifiLinkId(null,desk)).toBe('pi5>unoq:wifi')
})
test('one-spot advice uses compass words while the old desk keeps its sides',()=>{
 expect(moveWords({move_m:[-0.3,0]},true,layout)).toBe('30 cm west')
 expect(moveWords({move_m:[0.3,0]},true,layout)).toBe('30 cm east')
 expect(moveWords({move_m:[-0.3,0]},true,desk)).toBe('30 cm left')
})
test('an old multi-zone prediction cannot give a one-spot screen two sides',()=>{
 const state=mockState('between',0,7000)
 expect(judgeMoment(state,false,layout)[0]).not.toMatch(/two zones|left|right/i)
 expect(judgeMoment(state,false,desk)[0]).toBe('Between two zones')
})
