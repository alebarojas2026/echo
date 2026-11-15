import {expect,test} from 'vitest'
import {storyView,recordNumbers} from './ask-story'
import type {AskResponse} from './ask-client'
const reply:AskResponse={answer:'At 06:01 someone arrived.',rows:[{at:'06:01',t:1000,text:'Someone arrived.',cites:[12]}],tool:'story',ms:3,steps:[{tool:'records',ms:0,rows:2}],cites:[12],chain_ok:true}
test('uses board clock text, measured zero and exact record numbers',()=>{
 expect(storyView(reply)).toMatchObject({warning:'',rows:[{time:'06:01',text:'Someone arrived.',cites:[12]}],steps:['records · 0 ms · 2 rows'],cites:[12]})
})
test('a failed chain puts the board warning first without pretending the timeline verified',()=>{
 const warning='Warning: the sealed record does not check out at record 12, so this story cannot be trusted.'
 expect(storyView({...reply,chain_ok:false,answer:warning+' Someone arrived.'})?.warning).toBe(warning)
})
test('older boards use the answer alone; empty stories retain the answer',()=>{
 expect(storyView({...reply,steps:undefined})).toBeNull()
 expect(storyView({...reply,steps:[]})).toBeNull()
 expect(storyView({...reply,rows:[],answer:'No sealed records yet.'})?.fallback).toBe('No sealed records yet.')
})
test('missing measurements and clock times are never invented',()=>{
 expect(storyView({...reply,rows:[{text:'No time supplied.'}],steps:[{tool:'verify',ms:null,rows:null}] })).toMatchObject({rows:[{time:'__'}],steps:['verify · __ ms · __ rows']})
 expect(recordNumbers([0,-1,12,12,2.5,'17',Infinity])).toEqual([12])
})
