import { vi } from 'vitest'
// These legacy scenarios deliberately exercise the two-zone desk fixture.
vi.mock('../../../radio/nodes.json', async () => ({ default: (await import('../../tests/fixtures/desk-layout.json')).default }))
import { expect, test } from 'vitest'
import { mockState } from './mock-layout'
import { hudLayout } from './layout'
import { cameraLine, RadioOnlyClock } from './judge-camera-panel'
test('explains camera agreement, unplug and stalled states', () => {
  const state = mockState('camera', 0, 1000)
  state.teacher = { present: true, zone: state.pred!.zone, motion: 'still' }
  expect(cameraLine(state)).toContain('agrees')
  state.teacher.zone = hudLayout.zones.at(-1)!.id
  state.pred!.zone = hudLayout.zones[0].id
  expect(cameraLine(state)).not.toContain('agrees')
  state.cam = 'off'
  expect(cameraLine(state)).toBe('Camera unplugged · radio only')
  state.cam = 'stalled'
  expect(cameraLine(state)).toBe('Camera stalled · radio only')
})

test('unplug counter follows board time, stops on camera return, and resets without inventing a start', () => {
  const clock = new RadioOnlyClock(), state = mockState('still',0,7000)
  state.cam='off'; state.t=1000
  expect(clock.update(state)).toBeNull()
  state.cam='on'; clock.update(state)
  expect(cameraLine(state)).toMatch(/^Camera teaching/)
  state.cam='off'; state.t=2000
  expect(cameraLine(state,clock.update(state))).toBe('Radio only · 0:00')
  state.t=9000
  expect(cameraLine(state,clock.update(state))).toBe('Radio only · 0:07')
  state.t=63000
  expect(cameraLine(state,clock.update(state))).toBe('Radio only · 1:01')
  clock.reset()
  expect(clock.update(state)).toBeNull()
  state.cam='on'; expect(clock.update(state)).toBeNull()
})

test('an unknown camera cannot claim it was unplugged', () => {
 const state = mockState('still', 0, 1000)
 expect(cameraLine({ ...state, cam: 'unknown' as unknown as typeof state.cam })).toBe('Camera status unknown')
})
