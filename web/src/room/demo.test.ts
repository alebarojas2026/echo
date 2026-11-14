import { describe, expect, it } from 'vitest'
import { DEMO_MS } from './demo'
import { mockState } from './mock'

const start = 1_763_149_500_000
const at = (s: number) => mockState('demo', 1, s * 1000, 'S-home', start)

describe('self-playing demo', () => {
  it('starts with an empty square and the setup camera on', () => {
    const s = at(2)
    expect(s.pred!.present).toBe(false)
    expect(s.cam).toBe('on')
    expect(s.teacher).toEqual({ present: false, zone: 0, motion: null })
  })

  it('walks someone into zone 4, then counts the stillness and fires the alert at 10 s', () => {
    expect(at(6).pred).toMatchObject({ present: true, zone: 4, motion: 'moving' })
    expect(at(12).alert).toMatchObject({ state: 'counting', zone: 4 })
    expect(at(20).alert).toMatchObject({ state: 'check_on', zone: 4 })
  })

  it('clears the alert with a wave check-in, then unplugs the camera', () => {
    const s = at(26)
    expect(s.alert!.state).toBe('none')
    expect(s.checkin).toEqual({ t: start + 25_000, link: 'pi5>unoq:wifi' })
    expect(at(33).cam).toBe('on')
    expect(at(35).cam).toBe('off')
    expect(at(35).teacher).toBeNull()
  })

  it('walks them to zone 2 and out, then shows the tray as an object, not a person', () => {
    expect(at(43).pred).toMatchObject({ present: true, zone: 2 })
    const tray = at(50)
    expect(tray.pred).toMatchObject({ present: false, kind: 'object' })
    expect(tray.objects).toHaveLength(1)
    expect(tray.advice).toBeNull()
  })

  it('gives advice, moves the router (pred pauses), and reports a stronger link', () => {
    expect(at(58).advice?.to_spot).toBe('S-W30')
    const moved = at(63)
    expect(moved.router).toBe('S-W30')
    expect(moved.pred).toBeNull()
    expect(moved.advice!.after_dbm).toBeNull()
    const result = at(70).advice!
    expect(result.after_dbm).not.toBeNull()
    expect(result.after_dbm!).toBeGreaterThan(result.before_dbm!)
  })

  it('narrates each beat with a template sentence about 6 s late, and loops', () => {
    expect(at(9).narration).toBeNull()
    expect(at(11).narration).toMatchObject({ source: 'template', text: expect.stringContaining('zone 4') })
    expect(at(41).narration!.text).toContain('radio alone')
    const again = mockState('demo', 1, DEMO_MS + 2000, 'S-home', start)
    expect(again.pred!.present).toBe(false)
    expect(again.router).toBe('S-home')
    expect(again.checkin).toBeNull()
  })
})
