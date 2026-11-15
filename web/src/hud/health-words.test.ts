import {expect,test} from 'vitest'
import desk from '../../tests/fixtures/desk-layout.json'
import {mockState} from './mock-layout'
import {blindSentence} from './health-words'
const state=(nodes:string[])=>{const s=mockState('blind',0,1000);s.health.blind=desk.links.filter(l=>nodes.includes(l.tx)||nodes.includes(l.rx)).map(l=>l.id);return s}
test('names one beacon, a Pi, and two devices from the layout',()=>{
 expect(blindSentence(state(['east']),desk)).toBe('East beacon not heard. Check its power.')
 expect(blindSentence(state(['pi5b']),desk)).toBe('Pi B not heard. Check it is on the hotspot.')
 expect(blindSentence(state(['east','west']),desk)).toBe('East beacon and West beacon not heard. Check their power.')
})
test('ambiguous and unknown links do not blame a device or leak an id',()=>{
 const s=state([]);s.health.blind=['east>unoq:ble'];expect(blindSentence(s,desk)).toBe('A radio link is not heard.')
 s.health.blind=['secret-node>unknown:wifi'];expect(blindSentence(s,desk)).toBe('A radio link is not heard.')
})
