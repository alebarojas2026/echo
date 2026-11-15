import {expect,test} from 'vitest'
import {sourceWords} from './source-words'
import {mockState} from './mock-layout'
test('sources use words and live needs a heard radio link',()=>{
 const state=mockState('still',0,7000)
 expect(sourceWords(state)).toBe('Simulated')
 expect(sourceWords({...state,src:'replay'})).toBe('Replay')
 expect(sourceWords({...state,src:'live'})).toBe('Live')
 expect(sourceWords({...state,src:'live',links:[]})).toBe('No radio')
 expect(sourceWords(null)).toBe('No radio')
})
