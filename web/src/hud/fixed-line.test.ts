import {expect,test} from 'vitest'
import gate from '../../tests/fixtures/gate-layout.json'
import desk from '../../tests/fixtures/desk-layout.json'
import {deadZone,LineRecovery,holdAdvice} from './dead-zone'
import {mockState} from './mock-layout'
const id=gate.links.find(l=>l.kind==='wifi'&&l.crosses_spot)!.id
const state=(object:boolean,t:number,drop:number)=>({...mockState(object?'object':'empty',0,t),t,advice:null,links:[{id,dbm:-45-drop,base_dbm:-45,drop_db:drop,rate_hz:25,expected_hz:25,status:'ok',why:0}]})
test('only a confirmed object weakens the fixed-router story',()=>{
 const s=state(true,1000,16)
 expect(holdAdvice({...s,narration:{text:'Move the router 30 cm west',source:'template',event_id:'test',t:1000,gen_ms:null}},gate)?.narration).toBeNull()
 expect(deadZone(s,false,gate)?.text).toBe('Wi-Fi down 16.0 dB')
 expect(deadZone({...s,pred:{...s.pred!,kind:'person',present:true}},false,gate)).toBeNull()
 expect(deadZone(s,true,gate)).toBeNull()
 expect(deadZone({...s,links:[]},false,gate)).toBeNull()
 expect(deadZone({...s,advice:mockState('object',0,0).advice},false,desk)?.text).toMatch(/^Move the router/)
})
test('clearing the same link shows the measured gain and then expires',()=>{
 const history=new LineRecovery()
 history.update(state(true,1000,16),false,gate)
 expect(history.update(state(false,2000,1),false,gate)).toMatchObject({text:'+15.0 dB back',before:-61,after:-46})
 expect(history.update(state(false,9999,.2),false,gate)?.text).toBe('+15.0 dB back')
 expect(history.update(state(false,10000,.2),false,gate)).toBeNull()
})
test('missing data, clock resets and people cannot produce a recovered gain',()=>{
 for(const interrupt of ['stale','clock','person','reset']){
  const history=new LineRecovery();history.update(state(true,1000,16),false,gate)
  if(interrupt==='reset')history.reset()
  else if(interrupt==='clock')history.update(state(false,500,1),false,gate)
  else history.update({...state(false,1500,1),pred:interrupt==='person'?{...state(false,1500,1).pred!,present:true,kind:'person'}:null},interrupt==='stale',gate)
  expect(history.update(state(false,2000,1),false,gate)).toBeNull()
 }
})
