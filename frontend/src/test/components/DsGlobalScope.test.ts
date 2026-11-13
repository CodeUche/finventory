// The designer's look is the default for every screen: the page body carries the "ds" scope,
// the kit is loaded once at start-up, and the old one-off button classes are mapped in ds.css.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(__dirname, '../../..')
const read = (p: string) => readFileSync(resolve(root, p), 'utf8')

describe('global design scope', () => {
  it('puts the ds scope on the body so every page gets the kit', () => {
    expect(read('index.html')).toMatch(/<body class="[^"]*\bds\b/)
  })
  it('loads the kit at start-up, after the base styles', () => {
    const main = read('src/main.tsx')
    expect(main.indexOf("./styles/ds.css")).toBeGreaterThan(main.indexOf("./index.css"))
  })
  it('keeps the kit rules for old one-off buttons and pop-ups in one section', () => {
    const css = read('src/styles/ds.css')
    expect(css).toContain('GLOBAL COVERAGE')
    expect(css).toMatch(/\.bg-brand-500[^{]*\{[^}]*var\(--ds-btn\)/)
    expect(css).toContain('.ds .fixed.inset-0')
  })
  it('does not set padding on the shared button classes (small buttons must stay small)', () => {
    const css = read('src/styles/ds.css')
    expect(css).not.toMatch(/\.ds \.btn-(primary|secondary)\{[^}]*padding/)
  })
})
