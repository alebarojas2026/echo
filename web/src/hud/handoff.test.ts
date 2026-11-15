import {expect,test} from 'vitest'
import {handoff} from './handoff'
import {mockState} from './mock-layout'
const state=(cam:string,t:number)=>({...mockState('still',0,0),cam,t,handoff:{started_t:1000,radio_only_t:31000}} as unknown as ReturnType<typeof mockState>)
test('the handoff uses board timestamps across a new render or reload',()=>{
 const radio=handoff(state('off',91000),false)
 expect(radio.time).toBe('1:00');expect(radio.edge).toBe(true)
 expect(radio.teaching).toBe(.25);expect(radio.radio).toBe(.5)
 expect(handoff(state('off',91000),false)).toEqual(radio)
})
test('unknown, stalled and stale never claim radio only',()=>{
 for(const cam of ['unknown','stalled'])expect(handoff(state(cam,91000),false).phase).toBe('unknown')
 expect(handoff(state('off',91000),true).edge).toBe(false)
})
test('missing or future timing cannot start a browser-local run',()=>{
 const s=mockState('still',0,0);s.cam='off'
 expect(handoff(s,false).time).toBe('');expect(handoff(s,false).edge).toBe(false)
 expect(handoff(state('off',20000),false)).toMatchObject({time:'',teaching:0,radio:0,edge:false})
})
test('teaching progress uses measured counts and fits',()=>{
 const s=state('on',13000);s.model!.training={lesson:{started_t:1000,agree:6,of:10,fits:2,fitting:true}}
 expect(handoff(s,false)).toMatchObject({title:'CAMERA TEACHING',time:'0:12',detail:'6 of 10 agree · 2 fits · Fitting'})
})
