import { describe, expect, it } from 'vitest'
import { shownBrandColor, withShownBrand, DEFAULT_BRAND_COLOR } from '@/lib/brandColor'

describe('document brand colour', () => {
  it('shows the designer blue for the old server default or nothing', () => {
    expect(shownBrandColor('#F97316')).toBe(DEFAULT_BRAND_COLOR)
    expect(shownBrandColor('#f97316')).toBe(DEFAULT_BRAND_COLOR)
    expect(shownBrandColor(null)).toBe(DEFAULT_BRAND_COLOR)
    expect(shownBrandColor('')).toBe(DEFAULT_BRAND_COLOR)
  })
  it('keeps a colour someone chose', () => {
    expect(shownBrandColor('#0A6B0A')).toBe('#0A6B0A')
  })
  it('only rewrites the organisation when it has to', () => {
    const org = { id: 'o1', brand_color: '#0A6B0A' }
    expect(withShownBrand(org)).toBe(org)
    expect(withShownBrand({ id: 'o2', brand_color: '#f97316' }).brand_color).toBe(DEFAULT_BRAND_COLOR)
    expect(withShownBrand(null)).toBeNull()
  })
})
