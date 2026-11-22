// Messages and notification contrast: the chat bubble colours, the button hover rule and the
// bell action pills. These read the real kit file (src/styles/ds.css) and check the colour pairs
// against the WCAG minimum, so a future edit that makes text hard to read fails here.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { bubbleClass, TEAMMATE_PALETTE } from '@/lib/chatBubbles'

const root = resolve(__dirname, '../../..')
const read = (p: string) => readFileSync(resolve(root, p), 'utf8')
const css = read('src/styles/ds.css')

function lum(hex: string): number {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  const f = (x: number) => (x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4))
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function ratio(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
function token(scope: 'dark' | 'light', name: string): string {
  const re =
    scope === 'light'
      ? new RegExp(`html\\.light \\.ds\\{[^}]*?${name}:(#[0-9A-Fa-f]{6})`)
      : new RegExp(`\\.ds\\{[^}]*?${name}:(#[0-9A-Fa-f]{6})`)
  const m = css.match(re)
  if (!m) throw new Error(`token ${name} (${scope}) not found`)
  return m[1]
}

describe('chat bubbles', () => {
  it('uses the kit bubble classes, not text-white (the light theme turns text-white dark)', () => {
    expect(bubbleClass('mine')).toBe('chat-bubble-mine')
    expect(bubbleClass('theirs')).toBe('chat-bubble-theirs')
    const page = read('src/pages/messaging/MessagesPage.tsx')
    expect(page).toContain("bubbleClass('mine')")
    expect(page).not.toMatch(/mine \? 'bg-brand-500 text-white'/)
  })

  it('sets the bubble text colour on the elements inside the bubble too (html.light p would override it)', () => {
    expect(css).toMatch(/\.ds \.chat-bubble-mine :is\(p,[^)]*\)\{color:var\(--ds-bubble-mine-tx\)\}/)
    expect(css).toMatch(/\.ds \.chat-bubble-theirs :is\(p,[^)]*\)\{color:var\(--ds-bubble-theirs-tx\)\}/)
  })

  it('sent bubble is primary blue #1558EA with white text, at least 4.5:1', () => {
    const bg = token('dark', '--ds-bubble-mine')
    const tx = token('dark', '--ds-bubble-mine-tx')
    expect(bg.toLowerCase()).toBe('#1558ea')
    expect(tx.toLowerCase()).toBe('#ffffff')
    expect(ratio(bg, tx)).toBeGreaterThanOrEqual(4.5)
  })

  it('received bubble text reads on the lavender tint in light mode, at least 4.5:1', () => {
    const bg = token('light', '--ds-bubble-theirs')
    const tx = token('light', '--ds-bubble-theirs-tx')
    expect(ratio(bg, tx)).toBeGreaterThanOrEqual(4.5)
  })

  it('every teammate name colour has a deep light-page shade and a pale dark-page shade', () => {
    for (const c of TEAMMATE_PALETTE) {
      expect(c.text).toMatch(/^text-\w+-(800|900) dark:text-\w+-300$/)
    }
  })
})

describe('button hover never fades', () => {
  it('leaves filled buttons out of the translucent hover tint rule', () => {
    const rule = css.match(/\.ds :is\(button,a\):is\(\[class\*="hover:bg-surface-"\][^{]*\{/)
    expect(rule).not.toBeNull()
    expect(rule![0]).toContain(':not(:is(.bg-brand-400,.bg-brand-500,.bg-brand-600')
  })

  it('a filled button keeps its fill on hover and only lifts it', () => {
    expect(css).toMatch(
      /:not\(\.ds-tab\):hover:not\(:disabled\)\{\s*background:var\(--ds-btn\);filter:brightness\(1\.1\);/,
    )
  })

  it('filled buttons that carry text-always-white follow the kit button text colour', () => {
    expect(css).toMatch(/\.text-always-white:not\(\.btn-primary\)\{color:var\(--ds-btn-tx\) !important\}/)
  })
})

describe('bell action pills', () => {
  const bell = read('src/components/NotificationBell.tsx')
  it('use kit pill classes instead of translucent colour on colour', () => {
    expect(bell).toContain('notif-btn notif-btn-good')
    expect(bell).toContain('notif-btn notif-btn-bad')
    expect(bell).toContain('notif-btn notif-btn-neutral')
    expect(bell).not.toMatch(/bg-(green|emerald|red)-500\/20 text-(green|emerald|red)-400/)
  })
  it('pill text pairs with its fill at least 4.5:1 on the light page (dark fills are translucent; the audit script measures them on the real page)', () => {
    for (const k of ['green', 'red', 'gry']) {
      const bg = token('light', `--ds-pill-${k}-bg`)
      const tx = token('light', `--ds-pill-${k}-tx`)
      expect(ratio(bg, tx)).toBeGreaterThanOrEqual(4.5)
    }
  })
})
