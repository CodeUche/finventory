/**
 * Shared PDF header renderer — apply to every auto-generated document so the
 * template chosen in Settings → Templates is reflected globally.
 *
 * Callers must pre-load the logo as a base-64 data URL before invoking this
 * function (it is synchronous; async I/O must happen outside).
 */

type RGB = [number, number, number]

const SLATE4: RGB = [148, 163, 184]

export interface DocHeaderOptions {
  /** Template key: 'classic' | 'modern' | 'minimal' | 'professional' */
  tmpl: string
  pageW: number
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
 * Returns the Y coordinate where body content should start.
 */
export function applyDocHeader(doc: any, opts: DocHeaderOptions): number {
  const {
    tmpl, pageW,
    BRAND, DARK, MUTED,
    logoData,
    displayName,
    orgAddress, orgEmail, orgPhone,
    pdfFont     = 'helvetica',
    fontSize    = 14,
    pdfStyle    = 'bold',
    nameColor   = DARK,
    companyFontUnderline = false,
    showCompanyName = true,
    docTitle,
    metaRows    = [],
  } = opts

  let y = 0

  const addLogoIfPresent = (x: number, top: number, w = 22, h = 22) => {
    if (!logoData) return
    const fmt = logoData.includes('image/png') ? 'PNG' : 'JPEG'
    doc.addImage(logoData, fmt, x, top, w, h)
  }

  const drawUnderline = (x: number, yLine: number, color: RGB) => {
    const tw = doc.getTextWidth(displayName)
    doc.setDrawColor(...color); doc.setLineWidth(0.3)
    doc.line(x, yLine, x + tw, yLine)
  }

  // ── Classic ─────────────────────────────────────────────────────────────────
  if (tmpl === 'classic') {
    const H = 36
    doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, H, 'F')
    addLogoIfPresent(8, 6)
    const nameX = logoData ? 34 : 10
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nameColor)
      doc.text(displayName, nameX, 15)
      if (companyFontUnderline) drawUnderline(nameX, 16.5, nameColor)
    }
    doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(220, 220, 220)
    let iy = showCompanyName && displayName ? 21 : 14
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4 }
    if (orgPhone)   { doc.text(orgPhone,   nameX, iy); iy += 4 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }
    // Title (right)
    doc.setFontSize(20); doc.setFont('helvetica', 'bold'); doc.setTextColor(255, 255, 255)
    doc.text(docTitle, pageW - 10, 14, { align: 'right' })
    metaRows.forEach(([lbl, val], i) => {
      doc.setFontSize(7.5); doc.setFont('helvetica', 'normal'); doc.setTextColor(200, 200, 200)
      doc.text(lbl, pageW - 65, 20 + i * 5)
      doc.setFont('helvetica', 'bold'); doc.setTextColor(255, 255, 255)
      doc.text(val, pageW - 10, 20 + i * 5, { align: 'right' })
    })
    y = H + 8

  // ── Modern ──────────────────────────────────────────────────────────────────
  } else if (tmpl === 'modern') {
    doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, 4, 'F')
    y = 10
    addLogoIfPresent(14, y + 2)
    const nameX = logoData ? 40 : 14
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nameColor)
      doc.text(displayName, nameX, y + 12)
      if (companyFontUnderline) drawUnderline(nameX, y + 13.5, nameColor)
    }
    doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
    let iy = y + 18
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }
    // Title (right)
    doc.setFontSize(22); doc.setFont('helvetica', 'bold'); doc.setTextColor(...BRAND)
    doc.text(docTitle, pageW - 14, y + 12, { align: 'right' })
    if (metaRows.length > 0) {
      const boxH = Math.max(22, metaRows.length * 5.5 + 8)
      doc.setFillColor(248, 250, 252); doc.roundedRect(pageW - 76, y + 16, 62, boxH, 2, 2, 'F')
      metaRows.forEach(([lbl, val], i) => {
        doc.setFontSize(7.5); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
        doc.text(lbl, pageW - 73, y + 22 + i * 5.5)
        doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
        doc.text(val, pageW - 16, y + 22 + i * 5.5, { align: 'right' })
      })
    }
    y = y + 42
    doc.setDrawColor(...BRAND); doc.setLineWidth(0.5); doc.line(14, y, pageW - 14, y)
    y += 8

  // ── Minimal ─────────────────────────────────────────────────────────────────
  } else if (tmpl === 'minimal') {
    y = 12
    addLogoIfPresent(14, y)
    const nameX = logoData ? 40 : 14
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nameColor)
      doc.text(displayName, nameX, y + 10)
      if (companyFontUnderline) drawUnderline(nameX, y + 11.5, nameColor)
    }
    doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
    let iy = y + 16
    if (orgAddress) { doc.text(orgAddress, nameX, iy); iy += 4 }
    if (orgEmail)   { doc.text(orgEmail,   nameX, iy) }
    // Title (right)
    doc.setFontSize(20); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
    doc.text(docTitle, pageW - 14, y + 10, { align: 'right' })
    metaRows.forEach(([lbl, val], i) => {
      doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
      doc.text(lbl, pageW - 65, y + 17 + i * 5.5)
      doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text(val, pageW - 14, y + 17 + i * 5.5, { align: 'right' })
    })
    y = y + 32
    doc.setDrawColor(...DARK); doc.setLineWidth(1.2); doc.line(14, y, pageW - 14, y)
    y += 8

  // ── Professional ────────────────────────────────────────────────────────────
  } else {
    const H = 40
    const splitX = pageW * 0.46
    doc.setFillColor(...BRAND);         doc.rect(0,      0, splitX,        H, 'F')
    doc.setFillColor(248, 250, 252);    doc.rect(splitX, 0, pageW - splitX, H, 'F')
    addLogoIfPresent(8, 6)
    const nameX = logoData ? 33 : 10
    if (showCompanyName && displayName) {
      doc.setFontSize(fontSize); doc.setFont(pdfFont, pdfStyle); doc.setTextColor(...nameColor)
      doc.text(displayName, nameX, 16)
      if (companyFontUnderline) drawUnderline(nameX, 17.5, nameColor)
    }
    doc.setFontSize(8); doc.setFont('helvetica', 'normal'); doc.setTextColor(...SLATE4)
    let iy = 22
    if (orgAddress) { doc.text(orgAddress.slice(0, 30), nameX, iy); iy += 4 }
    if (orgEmail)   { doc.text(orgEmail, nameX, iy) }
    // Title (right panel)
    doc.setFontSize(15); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
    doc.text(docTitle, pageW - 14, 13, { align: 'right' })
    metaRows.forEach(([lbl, val], i) => {
      doc.setFontSize(7.5); doc.setFont('helvetica', 'normal'); doc.setTextColor(...SLATE4)
      doc.text(lbl, splitX + 5, 18 + i * 5.2)
      doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text(val, pageW - 14, 18 + i * 5.2, { align: 'right' })
    })
    y = H + 8
  }

  return y
}

/** Returns the table head fill color for a given template. */
export function templateHeadFill(tmpl: string, BRAND: RGB): RGB {
  const DARK_: RGB = [30, 30, 30]
  if (tmpl === 'minimal') return DARK_
  return BRAND
}

/** Returns true when alternate row shading should be white (minimal template). */
export function templateAltRowFill(tmpl: string): [number, number, number] {
  return tmpl === 'minimal' ? [255, 255, 255] : [248, 248, 248]
}

/** Returns table line color & width for a given template. */
export function templateTableLine(tmpl: string, DARK: RGB): { color: RGB; width: number } {
  return tmpl === 'minimal'
    ? { color: DARK, width: 0.4 }
    : { color: [225, 225, 225], width: 0.2 }
}
