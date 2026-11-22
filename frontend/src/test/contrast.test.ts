import { describe, expect, it } from 'vitest'
import { contrastRatio, onAccent } from '@/lib/contrast'

describe('onAccent', () => {
  it('uses white text on dark accents and dark text on light ones', () => {
    expect(onAccent('#12694A')).toBe('#FFFFFF')
    expect(onAccent('#1558EA')).toBe('#FFFFFF')
    expect(onAccent('#FECB01')).toBe('#111111')
    expect(onAccent('#E6E0FF')).toBe('#111111')
  })
  it('falls back to white for a value that is not a colour', () => {
    expect(onAccent('red')).toBe('#FFFFFF')
  })
  it('always gives at least 4.5:1 for the shop accents we ship and common picks', () => {
    for (const c of ['#12694A', '#1558EA', '#FECB01', '#CC0003', '#110099', '#13CC00', '#808080']) {
      expect(contrastRatio(c, onAccent(c))).toBeGreaterThanOrEqual(4.5)
    }
  })
})
