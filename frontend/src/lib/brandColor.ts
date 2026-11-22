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

export function withShownBrand<T extends { brand_color?: string | null; brand_color_raw?: string } | null>(org: T): T {
  if (!org) return org
  const shown = shownBrandColor(org.brand_color)
  if (shown === org.brand_color) return org
  // Remember what the server really holds, so a save that did not touch the colour can send it back unchanged.
  return { ...org, brand_color: shown, brand_color_raw: org.brand_color_raw ?? org.brand_color ?? undefined } as T
}

/** Value to send on save: the server's own value unless the user picked a different colour. */
export function brandColorToSave(current: string, raw?: string | null): string {
  if (raw !== undefined && raw !== null && shownBrandColor(raw) === current) return raw
  return current
}
