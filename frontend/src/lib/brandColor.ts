/**
 * The server stores #f97316 (orange) for every organisation that never picked a
 * document colour. Orange is not in the designer's palette, so that stored default
 * is shown as the designer's primary blue instead. A colour someone chose on
 * purpose is left alone. (The server default itself is a separate change.)
 */
export const DEFAULT_BRAND_COLOR = '#1558EA'
const OLD_DEFAULT = '#f97316'

export function shownBrandColor(hex?: string | null): string {
  if (!hex || hex.trim().toLowerCase() === OLD_DEFAULT) return DEFAULT_BRAND_COLOR
  return hex
}

export function withShownBrand<T extends { brand_color?: string | null } | null>(org: T): T {
  if (!org) return org
  const shown = shownBrandColor(org.brand_color)
  return shown === org.brand_color ? org : ({ ...org, brand_color: shown } as T)
}
