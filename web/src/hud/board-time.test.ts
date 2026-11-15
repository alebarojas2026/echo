import {expect,test,vi} from 'vitest'
import {boardNow} from './board-time'
import {mockState} from './mock-layout'
import {makeMockAskClient,boardAskClient} from './ask-client'
test('board time ignores the laptop epoch and follows monotonic elapsed time',()=>{
 const state=mockState('empty',0,1000);state.t=100000
 expect(boardNow({state,receivedAt:50},650)).toBe(100600)
 state.t=1000;expect(boardNow({state,receivedAt:650},750)).toBe(1100)
 expect(boardNow({state:null,receivedAt:null},750)).toBeNull()
})
test('mock answers cannot invent a record span before a board time exists',async()=>{
 await expect(makeMockAskClient(()=>null).ask('Was anyone here in the last 10 minutes?',new AbortController().signal)).rejects.toThrow('Waiting for the board time')
})

test('the real Ask client preserves the board response span and sends no laptop time',async()=>{
 const span={from_t:1000,to_t:121000}
 const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({answer:'Someone was here.',rows:[],tool:'presence',ms:40,span})})
 vi.stubGlobal('fetch',fetcher)
 try {
  expect((await boardAskClient.ask('Was anyone here?',new AbortController().signal)).span).toEqual(span)
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({question:'Was anyone here?'})
 } finally { vi.unstubAllGlobals() }
})
