import {expect,test} from 'vitest'
import {PlacementCheck} from './placement-check'
import {mockState} from './mock-layout'
import type {LinkState} from '../room/contract'
const link=(id:string,drop:number):LinkState=>({id,dbm:-60-drop,base_dbm:-60,drop_db:drop,rate_hz:8,expected_hz:8,status:'ok',why:0})
function capture(check:PlacementCheck) {
 check.begin()
 for(let i=0;i<=50;i++) check.update({...mockState('empty',i,0),t:10000+i*100,links:[link('quiet',i%2?0.1:-0.1),link('noisy',i%2?3:-3)]},false)
}
test('each link gets its own measured empty-room range',()=>{
 const check=new PlacementCheck();capture(check)
 expect(check.threshold(link('quiet',0))).toBeLessThan(1)
 expect(check.threshold(link('noisy',0))).toBeGreaterThan(8)
 expect(check.seen(link('quiet',3),false)).toBe(true)
 expect(check.seen(link('noisy',3),false)).toBe(false)
})
test('missing, stale, and unmeasured links never get a tick',()=>{
 const check=new PlacementCheck();capture(check)
 expect(check.seen(link('unmeasured',30),false)).toBe(false)
 expect(check.seen(link('quiet',30),true)).toBe(false)
 expect(check.seen({...link('quiet',30),status:'stale'},false)).toBe(false)
 expect(check.seen({...link('quiet',30),base_dbm:null},false)).toBe(false)
 expect(check.seen({...link('quiet',30),rate_hz:0},false)).toBe(false)
})
test('a new baseline, layout, or board restart invalidates the reference',()=>{
 const check=new PlacementCheck();capture(check)
 check.update({...mockState('empty',0,0),t:16000,links:[{...link('quiet',5),base_dbm:-70}]},false)
 expect(check.threshold(link('quiet',5))).toBeNull()
 capture(check);check.update({...mockState('empty',0,0),t:16000,links:[link('quiet',5)]},false,'new layout')
 expect(check.threshold(link('quiet',5))).toBeNull()
 capture(check);check.update({...mockState('empty',0,0),t:1,links:[link('quiet',5)]},false)
 expect(check.threshold(link('quiet',5))).toBeNull()
})
test('repeated states and short bursts cannot pretend to measure five seconds',()=>{
 const check=new PlacementCheck();check.begin()
 const state={...mockState('empty',0,0),t:1000,links:[link('quiet',0)]}
 for(let i=0;i<100;i++)check.update(state,false)
 check.update({...state,t:6000},false)
 expect(check.threshold(link('quiet',0))).toBeNull()
})
test('a long interruption aborts the capture; replay cannot calibrate',()=>{
 const check=new PlacementCheck();check.begin()
 const state={...mockState('empty',0,0),t:1000,links:[link('quiet',0)]}
 check.update(state,false);check.update({...state,t:9000},false)
 expect(check.capturing).toBe(false)
 expect(check.threshold(link('quiet',0))).toBeNull()
 check.begin();check.update({...state,src:'replay'},false)
 expect(check.elapsed).toBe(0)
 expect(check.threshold(link('quiet',0))).toBeNull()
})
