import {expect,test} from 'vitest'
import {readChain,chainLine} from './chain-status'
const chain={seq:4127,verified:true,witnesses_ok:2,witnesses:2}
test('missing and malformed chain data stays absent',()=>{
 for(const state of [null,{}, {chain:null},{chain:{seq:-1,verified:true}},{chain:{seq:1,verified:null}}])expect(readChain(state)).toBeNull()
 expect(readChain({chain})).toEqual(chain)
})
test('the state supplies the verification and witness counts',()=>{
 expect(chainLine(chain,false,null)).toEqual({text:'Sealed record · verified · 2 witnesses',fault:false})
 expect(chainLine({...chain,witnesses:0,witnesses_ok:0},false,null)).toEqual({text:'Sealed record · verified · 0 witnesses',fault:false})
 expect(chainLine({...chain,witnesses_ok:1},false,null).text).toContain('1 of 2 witnesses')
 expect(chainLine({...chain,witnesses:undefined},false,null).text).toContain('witnesses unavailable')
})
test('only an actual failure uses fault words, with a valid bad record when known',()=>{
 expect(chainLine({...chain,verified:false},false,4012)).toEqual({text:'Sealed record · record 4012 failed verification · 2 witnesses',fault:true})
 for(const bad of [null,0,Infinity,5000])expect(chainLine({...chain,verified:false},false,bad).text).toContain('· verification failed ·')
 expect(chainLine({...chain,verified:'checking'},false,null).text).toContain('· checking ·')
 expect(chainLine({...chain,seq:0},false,null).text).toContain('no records yet')
 expect(chainLine(chain,true,null)).toEqual({text:'Sealed record · waiting for board',fault:false})
})
