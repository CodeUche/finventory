/**
 * Shared PDF utilities — unified professional design system.
 *
 * Every PDF exported from Audity must use:
 *   - applyDocHeader()   → consistent header with logo, company info, doc title, meta grid
 *   - buildTableStyle()  → consistent table styling with brand header, alternating rows
 *   - addDocFooter()     → consistent footer on every page with brand accent bar on last page
 *
 * Callers must pre-load the logo as a base-64 data URL before invoking these
 * functions (they are synchronous; async I/O must happen outside).
 */

import { getActiveCurrency, getCurrencySymbol } from './utils'

export type RGB = [number, number, number]

// ── PDF-safe currency formatting ───────────────────────────────────────────────
// jsPDF's standard fonts (helvetica/times/courier) use WinAnsi encoding, which
// has no glyph for ₦ (U+20A6) — writing it into doc.text() renders a broken
// replacement-glyph box instead of the symbol. The web UI's formatCurrency()
// correctly shows ₦ (browsers render it via system fonts), but anything
// written into a jsPDF document must use these PDF-safe equivalents instead.
export function pdfCurrencySymbol(currency?: string): string {
  const cur = currency ?? getActiveCurrency()
  return cur === 'NGN' ? 'N' : getCurrencySymbol(cur)
}

export function pdfMoney(value: string | number, currency?: string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  const symbol = pdfCurrencySymbol(currency)
  if (isNaN(num)) return `${symbol}0.00`
  const sign = num < 0 ? '-' : ''
  const formatted = new Intl.NumberFormat('en', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(Math.abs(num))
  return `${sign}${symbol}${formatted}`
}

/** Formats a quantity for PDF/table display, dropping decimals for whole numbers (e.g. "3" not "3.00"). */
export function pdfQty(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return String(value)
  return num % 1 === 0 ? String(num) : String(parseFloat(num.toFixed(2)))
}

// ── Design system color palette ────────────────────────────────────────────────
export const COLORS = {
  DARK:  [22,  22,  30]  as RGB,   // near-black
  MID:   [75,  85,  99]  as RGB,   // slate-600
  MUTED: [107, 114, 128] as RGB,   // slate-500
  LIGHT: [248, 250, 252] as RGB,   // slate-50
  RULE:  [226, 232, 240] as RGB,   // slate-200 — divider lines
  WHITE: [255, 255, 255] as RGB,
  RED:   [185, 28,  28]  as RGB,
  GREEN: [21,  128, 61]  as RGB,
  AMBER: [180, 83,  9]   as RGB,
}

// ── Typography scale (pt) ──────────────────────────────────────────────────────
export const TYPE = {
  H1:    { size: 20, style: 'bold'   as const },  // document title
  H2:    { size: 12, style: 'bold'   as const },  // section labels
  H3:    { size: 9,  style: 'bold'   as const },  // column headers, sub-labels
  BODY:  { size: 8,  style: 'normal' as const },  // all body text
  SMALL: { size: 7,  style: 'normal' as const },  // footnotes, metadata, footer text
  TINY:  { size: 6.5,style: 'normal' as const },  // page stamps, fine print
}

export interface DocHeaderOptions {
  /** Template key: 'classic' | 'modern' | 'minimal' | 'professional' */
  tmpl: string
  pageW: number
  /** Whether this is a landscape document (affects margins) */
  landscape?: boolean
  /** Brand color (resolved from org.brand_color) */
  BRAND: RGB
  DARK:  RGB
  MUTED: RGB
  /** Pre-loaded base-64 data URL (or null / undefined if no logo) */
  logoData?: string | null
  /** Company display name */
  displayName: string
  orgAddress?: string
  orgEmail?: string
  orgPhone?: string
  /** jsPDF font family: 'helvetica' | 'times' | 'courier' */
  pdfFont?: string
  /** Company name font size */
  fontSize?: number
  /** Company name font style: 'normal' | 'bold' | 'italic' | 'bolditalic' */
  pdfStyle?: string
  /** Company name text color */
  nameColor?: RGB
  companyFontUnderline?: boolean
  /** When false, company name text is suppressed (logo-only mode) */
  showCompanyName?: boolean
  /** Document title, e.g. 'INVOICE', 'DELIVERY NOTE', 'VAT RETURN REPORT' */
  docTitle: string
  /** Key-value rows shown in the right meta panel */
  metaRows?: Array<[string, string]>
}

/**
 * Renders the document header on `doc` according to `opts.tmpl`.
 *
 * Unified header spec (all templates):
 *  1. Logo 20×20mm, top-left at y=14mm (portrait) or y=10mm (landscape)
 *  2. Company name H2 bold DARK, right of logo (or at margin if no logo)
 *  3. Company address/phone/email BODY MUTED, stacked below name, 4.5mm line height
 *  4. Document title H1 bold BRAND, top-right aligned
 *  5. Meta rows: SMALL MUTED label left + DARK value right, 4mm line height
 *  6. Full-width RULE divider 1.5mm below last header element, 0.3pt stroke
 *  7. Returns Y where body content should start (5mm below the rule)
 *
 * The 'classic' template retains its colored banner as the company info
 * background; 'professional' retains the split panel. 'modern' and 'minimal'
 * use white backgrounds. In all cases the typography scale and spacing are
 * consistent.
 */
export function applyDocHeader(doc: any, opts: DocHeaderOptions): number {
  const {
    tmpl, pageW,
    landscape = false,
    BRAND, DARK, MUTED,
    logoData,
    displayName,
    orgAddress, orgEmail, orgPhone,
    pdfFont     = 'helvetica',
    fontSize    = 12,
    pdfStyle    = 'bold',
    nameColor,
    companyFontUnderline = false,
    showCompanyName = true,
    docTitle,
    metaRows    = [],
  } = opts

  const RULE    = COLORS.RULE
  const WHITE   = COLORS.WHITE
  const LIGHT   = COLORS.LIGHT
  const margin  = landscape ? 10 : 14

  doc.setLineHeightFactor(1.15)

  // ── Logo helper ──────────────────────────────────────────────────────────────
  // Max bounding box the logo may occupy — actual render size is scaled down
  // from this to preserve the source image's aspect ratio.
  const LOGO_MAX_W = 36
  const LOGO_MAX_H = 22
  // Fallback used by layout math before the real size is known (e.g. when
  // logoData is present but dimensions haven't been measured yet).
  const LOGO_SIZE = LOGO_MAX_H
  let logoRenderW = 0
  let logoRenderH = 0
  if (logoData) {
    try {
      const props = doc.getImageProperties(logoData)
      const ratio = props.width / props.height
      if (ratio >= LOGO_MAX_W / LOGO_MAX_H) {
        logoRenderW = LOGO_MAX_W
        logoRenderH = LOGO_MAX_W / ratio
      } else {
        logoRenderH = LOGO_MAX_H
        logoRenderW = LOGO_MAX_H * ratio
      }
    } catch {
      logoRenderW = LOGO_MAX_H
      logoRenderH = LOGO_MAX_H
    }
  }
  const addLogoIfPresent = (x: number, top: number) => {
    if (!logoData) return
    const fmt = logoData.includes('image/png') ? 'PNG'
      : logoData.includes('image/webp') ? 'WEBP'
      : 'JPEG'
    // Vertically center within the LOGO_MAX_H box so smaller/wider logos
    // don't hug the top edge.
    const yOffset = (LOGO_MAX_H - logoRenderH) / 2
    doc.addImage(logoData, fmt, x, top + yOffset, logoRenderW, logoRenderH)
  }

  // ── Underline helper for company name ────────────────────────────────────────
  const drawUnderline = (x: number, yLine: number, color: RGB, text: string) => {
    const tw = doc.getTextWidth(text)
    doc.setDrawColor(...color); doc.setLineWidth(0.3)
    doc.line(x, yLine, x + tw, yLine)
  }

  // ── Classic ─────────────────────────────────────────────────────────────────
  if (tmpl === 'classic') {
    const logoTop = 8
    const bannerH = Math.max(44, 16 + (metaRows.length * 4) + 4)
    doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, bannerH, 'F')

    // Logo
    addLogoIfPresent(margin, logoTop)
    const nameX = logoData ? margin + logoRenderW + 4 : margin

    // Company name
    if (showCompanyName && displayName) {
      const nc: RGB = nameColor ?? WHITE
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nc)
      doc.text(displayName, nameX, logoTop + 8)
      if (companyFontUnderline) drawUnderline(nameX, logoTop + 9.5, nc, displayName)
    }

    // Company details
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(220, 230, 245)
    let iy = (showCompanyName && displayName) ? logoTop + 14 : logoTop + 6
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4.5 }
    if (orgPhone)   { doc.text(orgPhone,   nameX, iy); iy += 4.5 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }

    // Document title — H1 bold WHITE top-right
    doc.setFontSize(TYPE.H1.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...WHITE)
    doc.text(docTitle, pageW - margin, logoTop + 8, { align: 'right' })

    // Meta rows — right-aligned grid below title
    let mY = logoTop + 14
    metaRows.forEach(([lbl, val]) => {
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(200, 210, 230)
      doc.text(lbl + ':', pageW - margin - 62, mY)
      doc.setFont(pdfFont, 'bold'); doc.setTextColor(...WHITE)
      doc.text(val, pageW - margin, mY, { align: 'right' })
      mY += 4
    })

    // Rule line below banner
    const ruleY = bannerH + 1.5
    doc.setDrawColor(...RULE); doc.setLineWidth(0.3)
    doc.line(margin, ruleY, pageW - margin, ruleY)
    return ruleY + 5

  // ── Modern ──────────────────────────────────────────────────────────────────
  } else if (tmpl === 'modern') {
    // Thin brand accent bar at top
    doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, 3, 'F')

    const logoTop = 10
    addLogoIfPresent(margin, logoTop)
    const nameX = logoData ? margin + logoRenderW + 4 : margin

    // Company name
    const nc: RGB = nameColor ?? DARK
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nc)
      doc.text(displayName, nameX, logoTop + 8)
      if (companyFontUnderline) drawUnderline(nameX, logoTop + 9.5, nc, displayName)
    }

    // Company details
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    let iy = (showCompanyName && displayName) ? logoTop + 14 : logoTop + 6
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4.5 }
    if (orgPhone)   { doc.text(orgPhone,   nameX, iy); iy += 4.5 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }

    // Document title — H1 BRAND top-right
    doc.setFontSize(TYPE.H1.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
    doc.text(docTitle, pageW - margin, logoTop + 8, { align: 'right' })

    // Meta box (LIGHT fill, RULE border, right side)
    if (metaRows.length > 0) {
      const boxH = metaRows.length * 4 + 8
      const boxTop = logoTop + 13
      const boxLeft = pageW - margin - 68
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(boxLeft, boxTop, 68, boxH, 2, 2, 'FD')
      let mY = boxTop + 5.5
      metaRows.forEach(([lbl, val]) => {
        doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
        doc.text(lbl + ':', boxLeft + 3, mY)
        doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
        doc.text(val, boxLeft + 65, mY, { align: 'right' })
        mY += 4
      })
    }

    // Rule line
    const lastInfoY = Math.max(
      (showCompanyName && displayName ? logoTop + 14 : logoTop + 6)
      + (orgAddress ? 4.5 : 0) + (orgPhone ? 4.5 : 0) + (orgEmail ? 4.5 : 0),
      (metaRows.length > 0 ? logoTop + 13 + metaRows.length * 4 + 8 : logoTop + LOGO_SIZE)
    )
    const ruleY = lastInfoY + 3
    doc.setDrawColor(...RULE); doc.setLineWidth(0.3)
    doc.line(margin, ruleY, pageW - margin, ruleY)
    return ruleY + 5

  // ── Minimal ─────────────────────────────────────────────────────────────────
  } else if (tmpl === 'minimal') {
    const logoTop = 14
    addLogoIfPresent(margin, logoTop)
    const nameX = logoData ? margin + logoRenderW + 4 : margin

    // Company name — DARK
    const nc: RGB = nameColor ?? DARK
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nc)
      doc.text(displayName, nameX, logoTop + 8)
      if (companyFontUnderline) drawUnderline(nameX, logoTop + 9.5, nc, displayName)
    }

    // Company details
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    let iy = (showCompanyName && displayName) ? logoTop + 14 : logoTop + 6
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4.5 }
    if (orgPhone)   { doc.text(orgPhone,   nameX, iy); iy += 4.5 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }

    // Document title — H1 DARK top-right
    doc.setFontSize(TYPE.H1.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
    doc.text(docTitle, pageW - margin, logoTop + 8, { align: 'right' })

    // Meta rows — plain right-aligned
    let mY = logoTop + 14
    metaRows.forEach(([lbl, val]) => {
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
      doc.text(lbl + ':', pageW - margin - 62, mY)
      doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
      doc.text(val, pageW - margin, mY, { align: 'right' })
      mY += 4
    })

    // Rule line — bold DARK for minimal template
    const lastInfoY = Math.max(
      (showCompanyName && displayName ? logoTop + 14 : logoTop + 6)
      + (orgAddress ? 4.5 : 0) + (orgPhone ? 4.5 : 0) + (orgEmail ? 4.5 : 0),
      mY
    )
    const ruleY = lastInfoY + 3
    doc.setDrawColor(...DARK); doc.setLineWidth(0.8)
    doc.line(margin, ruleY, pageW - margin, ruleY)
    return ruleY + 5

  // ── Professional ────────────────────────────────────────────────────────────
  } else {
    const bannerH = Math.max(44, 16 + (metaRows.length * 4) + 4)
    const splitX = pageW * 0.46

    // Two-panel background
    doc.setFillColor(...BRAND);    doc.rect(0,      0, splitX,          bannerH, 'F')
    doc.setFillColor(...LIGHT);    doc.rect(splitX, 0, pageW - splitX,  bannerH, 'F')

    // Logo
    const logoTop = 8
    addLogoIfPresent(margin, logoTop)
    const nameX = logoData ? margin + logoRenderW + 4 : margin

    // Company name (left panel — white on brand bg)
    const nc: RGB = nameColor ?? WHITE
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nc)
      doc.text(displayName, nameX, logoTop + 8)
      if (companyFontUnderline) drawUnderline(nameX, logoTop + 9.5, nc, displayName)
    }

    // Company details (left panel)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(210, 220, 240)
    let iy = (showCompanyName && displayName) ? logoTop + 14 : logoTop + 6
    if (orgAddress) { doc.text(orgAddress.slice(0, 32), nameX, iy); iy += 4.5 }
    if (orgPhone)   { doc.text(orgPhone, nameX, iy); iy += 4.5 }
    if (orgEmail)   { doc.text(orgEmail, nameX, iy) }

    // Document title (right panel) — H1 DARK
    doc.setFontSize(TYPE.H1.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
    doc.text(docTitle, pageW - margin, logoTop + 8, { align: 'right' })

    // Meta rows (right panel)
    let mY = logoTop + 14
    metaRows.forEach(([lbl, val]) => {
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
      doc.text(lbl + ':', splitX + 5, mY)
      doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
      doc.text(val, pageW - margin, mY, { align: 'right' })
      mY += 4
    })

    // Rule line
    const ruleY = bannerH + 1.5
    doc.setDrawColor(...RULE); doc.setLineWidth(0.3)
    doc.line(margin, ruleY, pageW - margin, ruleY)
    return ruleY + 5
  }
}

/**
 * Builds a consistent autoTable style object for all documents.
 *
 * Usage:
 *   const ts = buildTableStyle(BRAND, pdfFont, { landscape: false })
 *   autoTable(doc, { ...ts, startY: y, head: [...], body: [...], columnStyles: { ... } })
 */
export function buildTableStyle(
  BRAND: RGB,
  font = 'helvetica',
  opts: { landscape?: boolean } = {},
): Record<string, any> {
  const margin = opts.landscape ? 10 : 14
  return {
    styles: {
      font,
      fontSize: TYPE.BODY.size,
      cellPadding: { top: 2.8, right: 3.5, bottom: 2.8, left: 3.5 },
      lineColor: COLORS.RULE,
      lineWidth: 0.2,
      textColor: COLORS.DARK,
      valign: 'middle' as const,
      // Wrap long content onto extra lines (row grows) instead of cutting
      // it off — every exported document must show data in full.
      overflow: 'linebreak' as const,
    },
    headStyles: {
      fillColor: BRAND,
      textColor: COLORS.WHITE,
      fontStyle: 'bold' as const,
      fontSize: 7.5,
      cellPadding: { top: 3, right: 3.5, bottom: 3, left: 3.5 },
    },
    alternateRowStyles: {
      fillColor: COLORS.LIGHT,
    },
    tableLineColor: COLORS.RULE,
    tableLineWidth: 0.25,
    rowPageBreak: 'avoid' as const,
    showHead: 'everyPage' as const,
    margin: { left: margin, right: margin },
  }
}

/**
 * Adds a consistent footer on every page of the document.
 *
 * Footer layout (all pages):
 *   Left:   orgName · "Generated by Audity" · timestamp  — TINY MUTED
 *   Center: docTitle + docRef (e.g. "Invoice INV-A3F2-000001") — TINY MUTED
 *   Right:  "Page X of Y" — TINY MUTED
 *   Above text: 0.25pt RULE line spanning full content width
 *
 * Last page only: 2mm BRAND-colored accent bar flush with bottom of page.
 */
export function addDocFooter(
  doc: any,
  opts: {
    orgName: string
    docTitle: string
    docRef?: string
    BRAND: RGB
    pdfFont?: string
    landscape?: boolean
  },
) {
  const { orgName, docTitle, docRef = '', BRAND, pdfFont = 'helvetica', landscape = false } = opts
  const margin = landscape ? 10 : 14
  const pageCount: number = (doc.internal as any).getNumberOfPages()
  const timestamp = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const centerText = docRef ? `${docTitle}  ${docRef}` : docTitle

  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i)
    const pageW = doc.internal.pageSize.getWidth()
    const pageH = doc.internal.pageSize.getHeight()
    const footerLineY = pageH - 10

    // Rule above footer
    doc.setDrawColor(...COLORS.RULE); doc.setLineWidth(0.25)
    doc.line(margin, footerLineY, pageW - margin, footerLineY)

    // Footer text
    doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...COLORS.MUTED)
    doc.text(`${orgName}  ·  Generated by Audity  ·  ${timestamp}`, margin, footerLineY + 3.5)
    doc.text(centerText, pageW / 2, footerLineY + 3.5, { align: 'center' })
    doc.text(`Page ${i} of ${pageCount}`, pageW - margin, footerLineY + 3.5, { align: 'right' })

    // Brand accent bar — last page only
    if (i === pageCount) {
      doc.setFillColor(...BRAND)
      doc.rect(0, pageH - 2, pageW, 2, 'F')
    }
  }
}

/** Returns the table head fill color for a given template. */
export function templateHeadFill(tmpl: string, BRAND: RGB): RGB {
  return tmpl === 'minimal' ? COLORS.DARK : BRAND
}

/** Returns alternate row fill for a given template. */
export function templateAltRowFill(tmpl: string): RGB {
  return tmpl === 'minimal' ? COLORS.WHITE : COLORS.LIGHT
}

/** Returns table line color & width for a given template. */
export function templateTableLine(tmpl: string, _DARK: RGB): { color: RGB; width: number } {
  return tmpl === 'minimal'
    ? { color: COLORS.DARK, width: 0.4 }
    : { color: COLORS.RULE, width: 0.25 }
}
