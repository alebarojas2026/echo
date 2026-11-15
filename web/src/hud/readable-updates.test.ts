import {expect,test} from 'vitest'
import {NumberCadence,ReadingHold} from './readable-updates'
import {stillness} from './judge-stillness-panel'
import {mockState} from './mock-layout'

test('numbers stay readable for one second while new readings arrive',()=>{
 const cadence=new NumberCadence()
 expect(cadence.take(0)).toBe(true)
 for(const t of [100,250,500,999]) expect(cadence.take(t)).toBe(false)
 expect(cadence.take(1000)).toBe(true)
 expect(cadence.take(1250)).toBe(false)
})
test('a sentence stays four seconds and stale data clears immediately',()=>{
 const hold=new ReadingHold()
 expect(hold.update('First sentence.',0)).toBe('First sentence.')
 expect(hold.update('Second sentence.',3999)).toBe('First sentence.')
 expect(hold.update('Latest sentence.',4000)).toBe('Latest sentence.')
 expect(hold.update('',4100,true)).toBe('')
})
test('a fired alert has the actual count once, with no second count',()=>{
 const state=mockState('still',0,7000)
 state.alert={...state.alert!,state:'check_on',still_s:13.8,limit_s:10}
 const value=stillness(state,false)
 expect(value.text).toMatch(/No movement .* · 13 s$/)
 expect(value.text).not.toContain('10')
 expect(value.detail).toBe('')
})
