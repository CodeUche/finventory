/** Contrast helpers (WCAG 2 relative luminance). */

function channel(v: number): number {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

export function luminance(hex: string): number | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const [r, g, b] = [0, 2, 4].map((i) => channel(parseInt(m[1].slice(i, i + 2), 16)))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrastRatio(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  if (la === null || lb === null) return 1
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/** White or near-black text, whichever reads better on a shop's own accent colour. */
export function onAccent(hex: string): '#FFFFFF' | '#111111' {
  if (luminance(hex) === null) return '#FFFFFF'
  return contrastRatio(hex, '#FFFFFF') >= contrastRatio(hex, '#111111') ? '#FFFFFF' : '#111111'
}
