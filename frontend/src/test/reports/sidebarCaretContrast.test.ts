import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { contrastRatio } from '@/lib/contrast'

const css = readFileSync('src/styles/app-shell.css', 'utf8')

/** Blend colour `fg` over `bg` at the given opacity (the caret is drawn with opacity). */
function blend(fg: string, bg: string, a: number): string {
  const n = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
  const f = n(fg)
  const b = n(bg)
  return '#' + f.map((c, i) => Math.round(c * a + b[i] * (1 - a)).toString(16).padStart(2, '0')).join('')
}

describe('sidebar active-row caret', () => {
  const light = /--sh-active-bg:(#[0-9A-Fa-f]{6}); --sh-active-tx:(#[0-9A-Fa-f]{6})/.exec(css)!
  const opacity = Number(/\.sh-row-on \.sh-caret[^{]*\{opacity:([0-9.]+)\}/.exec(css)![1])

  it('was below 3:1 at the old strength (the reported miss)', () => {
    expect(contrastRatio(blend(light[2], light[1], 0.55), light[1])).toBeLessThan(3)
  })
  it('is at least 3:1 on the active tile in light mode now', () => {
    expect(contrastRatio(blend(light[2], light[1], opacity), light[1])).toBeGreaterThanOrEqual(3)
  })
})
