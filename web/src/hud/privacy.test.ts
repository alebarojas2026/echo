import { describe, expect, it } from 'vitest'
import { privacyMode } from './privacy'

const params = (query: string) => new URLSearchParams(query)

describe('privacyMode', () => {
  it('reads the board where the board feed is', () => {
    expect(privacyMode(params(''), true, false)).toBe('board')     // served by the board
    expect(privacyMode(params(''), false, true)).toBe('board')     // a built page
    expect(privacyMode(params('?src=ws'), false, false)).toBe('board')
  })
  it('is the mock only with the mock feed', () => {
    expect(privacyMode(params(''), false, false)).toBe('mock')     // the dev server
    expect(privacyMode(params('?mock=tour'), true, true)).toBe('mock')
    expect(privacyMode(params('?src=mock'), true, false)).toBe('mock')
  })
  it('can be picked in the address', () => {
    expect(privacyMode(params('?privacy=board'), false, false)).toBe('board')
    expect(privacyMode(params('?privacy=mock&src=ws'), true, true)).toBe('mock')
  })
})
