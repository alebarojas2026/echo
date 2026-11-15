import { expect, test } from 'vitest'
import { LessonProgress } from './lesson'
import { mockState } from './mock-layout'
const state = (t: number, training: unknown) => { const s = mockState('still', 1, 7000); s.t = t; s.model!.training = training; return s }
test('lesson words use board time and measured agreement only', () => {
  const p = new LessonProgress(), start = 100000
  expect(p.update(state(start, {lesson:{started_t:start,agree:0,of:0}}),false,0)?.line).toBe('Teaching the radio · 0 s')
  expect(p.update(state(start+12000, {lesson:{started_t:start,agree:2,of:3}}),false,1)).toEqual({line:'Teaching the radio · 12 s',agreement:'Radio agrees with the camera: 2 of 3',ratio:2/3})
  expect(p.update(state(start+12000, {lesson:{started_t:start,agree:6,of:10}}),false,2)?.ratio).toBe(.6)
  expect(p.update(state(start+13000, {lesson:{started_t:start,agree:2,of:2}}),false,3)?.agreement).toBe('')
  expect(p.update(state(start+31000,null),false,4)?.line).toBe('Taught in 31 s')
  expect(p.update(state(start+35000,null),false,4004)).toBeNull()
})
test('plain fits and missing or invalid readings stay honest', () => {
  const p=new LessonProgress()
  expect(p.update(state(5000,{started_t:1000}),false)?.line).toBe('Training · 4 s')
  expect(p.update(state(5000,{}),false)?.line).toBe('Training · __ s')
  expect(p.update(state(5000,{lesson:{started_t:1000,agree:8,of:3}}),false)?.agreement).toBe('')
  expect(p.update(state(5000,{}),true)).toBeNull()
})

