import { expect, test } from 'vitest'
import { mockState } from './mock-layout'
import { hudLayout } from './layout'
import { cameraLine } from './judge-camera-panel'
test('explains camera agreement, unplug and stalled states', () => {
  const state = mockState('camera', 0, 1000)
  state.teacher = { present: true, zone: state.pred!.zone, motion: 'still' }
  expect(cameraLine(state)).toContain('agrees')
  state.teacher.zone = hudLayout.zones.at(-1)!.id
  state.pred!.zone = 0 // the radio says nobody: that holds on a layout with one zone too
  expect(cameraLine(state)).not.toContain('agrees')
  state.cam = 'off'
  expect(cameraLine(state)).toBe('Camera unplugged · radio only')
  state.cam = 'stalled'
  expect(cameraLine(state)).toBe('Camera stalled · radio only')
})
