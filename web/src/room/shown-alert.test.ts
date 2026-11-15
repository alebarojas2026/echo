import { describe, expect, it } from 'vitest'
import { motionWord, shownAlert } from './shown-alert'
import type { Alert, Pred } from './contract'

const LINE = 'pi5>pi5b:wifi'
const up: Alert = { state: 'check_on', zone: 1, still_s: 26, limit_s: 10 }
const counting: Alert = { state: 'counting', zone: 1, still_s: 9, limit_s: 10 }
const person = (motion: string): Pred => ({ present: true, kind: 'person', zone: 1, zone_set: [1], motion, why: [LINE] }) as unknown as Pred
const nobody = { present: false, kind: 'none', zone: 0, zone_set: [], motion: null, why: [] } as unknown as Pred

describe('one decision for the no-movement alert and the motion word', () => {
  it('an empty spot never carries an alert on a layout with a presence line', () => {
    // What the kit showed for two seconds: "Nobody is here" with the alert still in the state.
    expect(shownAlert({ alert: { ...up, still_s: 0 }, pred: nobody }, LINE)?.state).toBe('none')
    expect(shownAlert({ alert: counting, pred: nobody }, LINE)?.state).toBe('none')
    expect(shownAlert({ alert: up, pred: person('still') }, LINE)).toBe(up)
  })
  it('a hidden decision and every other layout keep the alert the board sent', () => {
    expect(shownAlert({ alert: up, pred: null }, LINE)).toBe(up)
    expect(shownAlert({ alert: up, pred: nobody }, null)).toBe(up)
    expect(shownAlert(null, LINE)).toBeNull()
  })
  it('"moving" never stands over "No movement"', () => {
    expect(motionWord({ alert: up, pred: person('moving') }, LINE)).toBe('still')
    expect(motionWord({ alert: counting, pred: person('moving') }, LINE)).toBe('moving')
    expect(motionWord({ alert: counting, pred: person('still') }, LINE)).toBe('still')
    expect(motionWord({ alert: up, pred: nobody }, LINE)).toBeNull()
  })
})
