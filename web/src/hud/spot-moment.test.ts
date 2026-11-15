import {expect,test} from 'vitest'
import gate from '../../tests/fixtures/gate-layout.json'
import desk from '../../tests/fixtures/desk-layout.json'
import {mockState} from './mock-layout'
import {judgeMoment} from './judge-moment'
import {spotMoment} from './spot-moment'
const wifi=gate.links.find(l=>l.kind==='wifi'&&l.crosses_spot)!.id
test('moving and still are separate board decisions even when old advice remains',()=>{
 const s=mockState('still',0,7000);s.advice=mockState('object',0,7000).advice
 for(const motion of ['moving','still'] as const){s.pred={...s.pred!,kind:'person',present:true,motion};expect(judgeMoment(s,false,gate)[0]).toBe(motion==='moving'?'Someone is here, moving':'Someone is here, standing still')}
 s.pred!.motion=null;expect(spotMoment(s,gate)?.[0]).toBe('Someone is here')
 expect(spotMoment(s,desk)).toBeNull()
})
test('an object with nobody present names the Wi-Fi line and only its fresh drop',()=>{
 const s=mockState('object',0,7000);s.links=[{id:wifi,status:'ok',dbm:-60,base_dbm:-50,drop_db:10,rate_hz:25,expected_hz:25,why:0}]
 expect(judgeMoment(s,false,gate)).toEqual(['Something was left in the Wi-Fi line','−10.0 dB'])
 s.links[0].status='stale';expect(judgeMoment(s,false,gate)[1]).toBe('')
 s.links[0].status='ok';s.links[0].drop_db=NaN;expect(judgeMoment(s,false,gate)[1]).toBe('')
 expect(judgeMoment(s,true,gate)[0]).toBe('No data')
 s.health.status='blind';expect(judgeMoment(s,false,gate)[0]).toBe('Sensor blind')
})
