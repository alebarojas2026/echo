import { describe, expect, it } from 'vitest'
import { FOUND_AFTER_MS, FOUND_FADE_MS, FOUND_GAP_MS, FOUND_HOLD_MS, PresentSince, arrivalStep } from './arrival'
import { CameraSeen } from './handoff'
import { hudLayout } from './layout'
import { mockState } from '../room/mock'

describe('the walk-up card follows the board clock', () => {
  it('steps only by how long the board has said a person is here', () => {
    expect(arrivalStep(null)).toBe('waiting')
    expect(arrivalStep(FOUND_AFTER_MS - 1)).toBe('waiting')
    expect(arrivalStep(FOUND_AFTER_MS)).toBe('found')
    expect(arrivalStep(FOUND_AFTER_MS + FOUND_HOLD_MS)).toBe('fading')
    expect(arrivalStep(FOUND_AFTER_MS + FOUND_HOLD_MS + FOUND_FADE_MS)).toBe('done')
    // A page that was away for a minute lands on the last step at once.
    expect(arrivalStep(60_000)).toBe('done')
  })
  it('counts from the first state that says a person, through one missing tick, and starts again after a real gap', () => {
    const since = new PresentSince(), t = 1_800_000_000_000
    expect(since.update(false, t)).toBeNull()
    expect(since.update(true, t + 100)).toBe(0)
    expect(since.update(true, t + 600)).toBe(500)
    expect(since.update(false, t + 700)).toBe(600)
    expect(since.update(true, t + 800)).toBe(700)
    expect(since.update(false, t + 800 + FOUND_GAP_MS)).toBe(700 + FOUND_GAP_MS)
    expect(since.update(false, t + 900 + FOUND_GAP_MS)).toBeNull()
    expect(since.update(true, t + 2000)).toBe(0)
    // No reading (no data) and a board clock that stepped back both start the count again.
    expect(since.update(true, null)).toBeNull()
    expect(since.update(true, t + 3000)).toBe(0)
    expect(since.update(true, t + 1000)).toBe(0)
  })
})

describe('a layout with a presence line has no camera', () => {
  const gate = { ...hudLayout, presence: { line: 'pi5>pi5b:wifi' } }
  const state = (cam: string) => ({ ...mockState('still', 0, 7000), cam }) as ReturnType<typeof mockState>
  it('keeps teaching panels off the one-spot judge screen', () => {
    const camera = new CameraSeen()
    expect(camera.absent(state('off'), gate)).toBe(true)
    expect(camera.absent(state('unknown'), gate)).toBe(true)
    expect(camera.absent(state('on'), gate)).toBe(true)
    expect(camera.absent(state('off'), gate)).toBe(true)
  })
  it('leaves every other layout as it was', () => {
    expect(new CameraSeen().absent(state('off'), { ...hudLayout, presence: null })).toBe(false)
  })
})

describe('the one spot says one thing about moving and still', () => {
  const gateLayout = { ...hudLayout, zones: [{ id: 1, name: 'At the desk', still_alert_s: 10 }], presence: { line: 'pi5>pi5b:wifi' } }
  const standing = (motion: string, alert: object) => ({ ...mockState('still', 0, 7000), router: 'S-home', pred: { present: true, kind: 'person', zone: 1, zone_set: [1], motion, why: [] }, alert }) as unknown as ReturnType<typeof mockState>
  it('the headline is "standing still" while the no-movement alert is up, whatever one decision says', async () => {
    const { spotMoment } = await import('./spot-moment')
    expect(spotMoment(standing('moving', { state: 'check_on', zone: 1, still_s: 26, limit_s: 10 }), gateLayout)?.[0]).toBe('Someone is here, standing still')
    expect(spotMoment(standing('moving', { state: 'counting', zone: 1, still_s: 3, limit_s: 10 }), gateLayout)?.[0]).toBe('Someone is here, moving')
  })
  it('the still count is not shown beside "moving", and no alert is shown on an empty spot', async () => {
    const { stillness } = await import('./judge-stillness-panel')
    const before = hudLayout.presence
    hudLayout.presence = gateLayout.presence
    try {
      expect(stillness(standing('moving', { state: 'counting', zone: 1, still_s: 9, limit_s: 10 }), false).text).toBe('')
      expect(stillness(standing('still', { state: 'counting', zone: 1, still_s: 9, limit_s: 10 }), false).text).toBe('Still for 9 s of 10')
      const left = { ...standing('still', { state: 'check_on', zone: 1, still_s: 0, limit_s: 10 }), checkin: null, pred: { present: false, kind: 'none', zone: 0, zone_set: [], motion: null, why: [] } } as unknown as ReturnType<typeof mockState>
      expect(stillness(left, false).text).toBe('')
    } finally { hudLayout.presence = before }
  })
})
