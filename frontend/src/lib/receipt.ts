/**
 * Thermal receipt printing.
 *
 * Rather than talk to a printer directly — which needs a driver per model and
 * does not work at all from a browser — we render an 80mm-wide page and hand it
 * to the operating system's print dialog. Every thermal printer in a Nigerian
 * shop is installed as a normal Windows/Android printer, so this reaches all of
 * them, including the printer built into a POS terminal.
 *
 * Six layouts share one data shape. The merchant picks one in
 * Settings → Templates and it applies to every receipt the app prints.
 */

export type ReceiptTemplate =
  | 'compact'
  | 'detailed'
  | 'branded'
  | 'classic_cash'
  | 'shop_barcode'
  | 'stay_folio'

export const RECEIPT_TEMPLATES: { value: ReceiptTemplate; label: string; blurb: string }[] = [
  { value: 'compact', label: 'Compact', blurb: 'Least paper per sale. For busy counters where the roll is a running cost.' },
  { value: 'detailed', label: 'Detailed', blurb: 'Full columns, tax breakdown, FIRS reference and a signature line.' },
  { value: 'branded', label: 'Branded', blurb: 'Logo leads, and you write the closing message.' },
  { value: 'classic_cash', label: 'Classic cash', blurb: 'The corner-shop slip — centred heading, dashed rules.' },
  { value: 'shop_barcode', label: 'Shop & barcode', blurb: 'Dotted leaders and a scannable barcode, so returns are looked up by scanning.' },
  { value: 'stay_folio', label: 'Stay folio', blurb: 'Dated charge lines for hotels and anywhere a customer runs a tab.' },
]

export interface ReceiptLine {
  name: string
  qty: number | string
  unit_price: number | string
  line_total: number | string
  /** Chosen modifier names, e.g. ["Large", "Extra chicken"] — printed under the line. */
  modifiers?: string[]
  /** Charge date, used by the stay-folio layout. */
  date?: string
  /** Line reference, used by the stay-folio layout. */
  ref?: string
}

export interface ReceiptPayment {
  method: string
  amount: number | string
}

export interface ReceiptData {
  merchant: string
  /** Merchant address from the organisation profile. Never re-typed per sale. */
  address?: string
  phone?: string
  tin?: string
  rcNumber?: string
  website?: string
  invoiceNumber: string
  date: string
  /** The signed-in user who recorded the sale. Printed above "Powered by Audity". */
  cashier?: string
  /** "Served by" at a till, "Raised by" for an invoice raised at a desk. */
  cashierLabel?: string
  customer?: string
  customerTin?: string
  lines: ReceiptLine[]
  subtotal: number | string
  tax?: number | string
  discount?: number | string
  total: number | string
  payments?: ReceiptPayment[]
  amountTendered?: number | string
  change?: number | string
  /** Merchant's own closing line, shown by the branded layout. */
  footerNote?: string
  /** FIRS invoice reference number, printed when the sale was cleared. */
  firsIrn?: string
  qrCodeBase64?: string
  /** Merchant logo as a data URI. Converted to 1-bit mono before printing. */
  logoDataUrl?: string | null
  template?: ReceiptTemplate
}

/**
 * Money for a receipt roll.
 *
 * Trailing ".00" is dropped — a receipt is read at a glance, and "95,000,000"
 * is quicker to scan than "95,000,000.00". Real kobo is always kept, so
 * 1,234.50 still prints in full.
 */
const money = (v: number | string): string => {
  const n = Number(v || 0)
  if (!isFinite(n)) return '0'
  const hasKobo = Math.round(Math.abs(n) * 100) % 100 !== 0
  return n.toLocaleString('en-NG', {
    minimumFractionDigits: hasKobo ? 2 : 0,
    maximumFractionDigits: 2,
  })
}

/** Quantity: never pads, but keeps a real fraction (1.5 kg stays 1.5). */
const qtyFmt = (v: number | string): string => {
  const n = Number(v || 0)
  if (!isFinite(n)) return '0'
  return n.toLocaleString('en-NG', { maximumFractionDigits: 3 })
}

const escape = (s: string) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string
  ))

/** Address is a free-text block in the profile — keep the merchant's own line breaks. */
const addressLines = (a?: string) =>
  String(a ?? '').split(/\r?\n/).map((l) => l.trim()).filter(Boolean)

const TENDER_LABEL: Record<string, string> = {
  cash: 'Cash',
  pos: 'Card',
  card: 'Card',
  bank_transfer: 'Transfer',
  cheque: 'Cheque',
  credit_applied: 'On account',
}

// ── Code 128B ────────────────────────────────────────────────────────────────
// A real encoder, not a decorative bar pattern: the shop_barcode layout exists
// so a returned item can be looked up by scanning the slip, and a barcode that
// does not scan would be worse than printing none. Each entry is the six
// alternating bar/space module widths for one symbol value.
const C128 = (
  '212222222122222221121223121322131222122213122312132212221213' +
  '221312231212112232122132122231113222123122123221223211221132' +
  '221231213212223112312131311222321122321221312212322112322211' +
  '212123212321232121111323131123131321112313132113132311211313' +
  '231113231311112133112331132131113123113321133121313121211331' +
  '231131213113213311213131311123311321331121312113312311332111' +
  '314111221411431111111224111422121124121421141122141221112214' +
  '112412122114122411142112142211241211221114413111241112134111' +
  '111242121142121241114212124112124211411212421112421211212141' +
  '214121412121111143111341131141114113114311411113411311113141' +
  '114131311141411131211412211214211232'
).match(/.{6}/g) as string[]
const C128_STOP = '2331112'

/**
 * Render `text` as a scannable Code 128B barcode SVG.
 * Returns an empty string for anything outside the printable ASCII the
 * symbology covers, rather than emitting bars a scanner would reject.
 */
export function code128Svg(text: string, height = 34): string {
  const chars = String(text ?? '')
  if (!chars || !/^[\x20-\x7E]+$/.test(chars)) return ''

  const values = [104] // Start B
  for (const ch of chars) values.push(ch.charCodeAt(0) - 32)

  let sum = values[0]
  for (let i = 1; i < values.length; i++) sum += values[i] * i
  values.push(sum % 103) // checksum

  const widths = values.map((v) => C128[v]).join('') + C128_STOP
  const total = [...widths].reduce((a, c) => a + Number(c), 0)

  let x = 0
  let bar = true
  const rects: string[] = []
  for (const c of widths) {
    const w = Number(c)
    if (bar) rects.push('<rect x="' + x + '" y="0" width="' + w + '" height="' + height + '"/>')
    x += w
    bar = !bar
  }
  return '<svg class="bc" viewBox="0 0 ' + total + ' ' + height + '" preserveAspectRatio="none" role="img" aria-label="' + escape(chars) + '"><g fill="#000">' + rects.join('') + '</g></svg>'
}

// ── Mono logo ────────────────────────────────────────────────────────────────
/**
 * Convert a logo to 1-bit black-and-white sized for an 80mm roll.
 *
 * A thermal head has no greys: it either burns a dot or it does not. Sending a
 * colour or photographic logo straight through prints a dark smear, so every
 * pixel is thresholded to solid black or dropped to white here, at roll width
 * rather than scaled down from whatever the merchant uploaded for A4.
 */
export function toMonoDataUrl(src: string, maxWidth = 180): Promise<string | null> {
  return new Promise((resolve) => {
    if (!src) { resolve(null); return }
    const img = new Image()
    img.crossOrigin = 'anonymous'
    // A logo that never loads must not hold the printer up.
    const timer = window.setTimeout(() => resolve(null), 2500)

    img.onload = () => {
      window.clearTimeout(timer)
      try {
        const scale = Math.min(1, maxWidth / (img.naturalWidth || maxWidth))
        const w = Math.max(1, Math.round((img.naturalWidth || maxWidth) * scale))
        const h = Math.max(1, Math.round((img.naturalHeight || maxWidth) * scale))
        const canvas = document.createElement('canvas')
        canvas.width = w; canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) { resolve(null); return }

        // Flatten onto white first: a transparent PNG would otherwise threshold
        // its own empty background to black.
        ctx.fillStyle = '#fff'
        ctx.fillRect(0, 0, w, h)
        ctx.drawImage(img, 0, 0, w, h)

        const data = ctx.getImageData(0, 0, w, h)
        const px = data.data
        for (let i = 0; i < px.length; i += 4) {
          const lum = 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2]
          const on = lum < 156
          px[i] = px[i + 1] = px[i + 2] = on ? 0 : 255
          px[i + 3] = 255
        }
        ctx.putImageData(data, 0, 0)
        resolve(canvas.toDataURL('image/png'))
      } catch {
        // A cross-origin logo taints the canvas and blocks toDataURL. The
        // receipt falls back to the business name rather than failing.
        resolve(null)
      }
    }
    img.onerror = () => { window.clearTimeout(timer); resolve(null) }
    img.src = src
  })
}

// ── Shared blocks ────────────────────────────────────────────────────────────
const logoImg = (d: ReceiptData, cls = '') =>
  d.logoDataUrl ? `<img class="logo ${cls}" src="${d.logoDataUrl}" alt="">` : ''

const addressBlock = (d: ReceiptData) =>
  addressLines(d.address).map((l) => `<div class="c small">${escape(l)}</div>`).join('')

const contactBlock = (d: ReceiptData) => [
  d.phone ? `<div class="c small">${escape(d.phone)}</div>` : '',
  d.tin ? `<div class="c small">TIN: ${escape(d.tin)}</div>` : '',
].join('')

/** Item name on its own row, quantity and price beneath. Survives long names. */
const stackedLines = (d: ReceiptData) => d.lines.map((l) => `
  <tr><td class="nm" colspan="3">${escape(l.name)}</td></tr>
  ${l.modifiers?.length ? `<tr><td class="mod" colspan="3">${escape(l.modifiers.join(', '))}</td></tr>` : ''}
  <tr>
    <td class="qty">${qtyFmt(l.qty)} ×</td>
    <td class="amt">${money(l.unit_price)}</td>
    <td class="amt">${money(l.line_total)}</td>
  </tr>`).join('')

/** True four-column table. Tight on 80mm, but exact for trade customers. */
const columnLines = (d: ReceiptData) => d.lines.map((l) => `
  <tr>
    <td class="nm4">${escape(l.name)}</td>
    <td class="amt">${qtyFmt(l.qty)}</td>
    <td class="amt">${money(l.unit_price)}</td>
    <td class="amt">${money(l.line_total)}</td>
  </tr>
  ${l.modifiers?.length ? `<tr><td class="mod" colspan="4">${escape(l.modifiers.join(', '))}</td></tr>` : ''}`).join('')

/** Dotted-leader rows, no table. */
const leaderLines = (d: ReceiptData) => d.lines.map((l) => `
  <div class="lead"><span>${escape(l.name)}</span><span class="fill"></span><span class="amt">${money(l.line_total)}</span></div>
  <div class="small ind">${qtyFmt(l.qty)} × ${money(l.unit_price)}</div>`).join('')

const totalsBlock = (d: ReceiptData, totalLabel = 'TOTAL') => `
  <table>
    <tr><td>Subtotal</td><td class="amt">${money(d.subtotal)}</td></tr>
    ${Number(d.discount || 0) ? `<tr><td>Discount</td><td class="amt">-${money(d.discount!)}</td></tr>` : ''}
    ${Number(d.tax || 0) ? `<tr><td>VAT</td><td class="amt">${money(d.tax!)}</td></tr>` : ''}
    <tr class="tot"><td>${totalLabel}</td><td class="amt">${money(d.total)}</td></tr>
  </table>`

const paymentsBlock = (d: ReceiptData) => {
  const rows = (d.payments ?? []).map((p) => `
    <tr><td>${escape(TENDER_LABEL[p.method] ?? p.method)}</td>
        <td class="amt">${money(p.amount)}</td></tr>`).join('')
  const tendered = Number(d.amountTendered || 0) ? `
    <tr><td>Tendered</td><td class="amt">${money(d.amountTendered!)}</td></tr>
    <tr><td>Change</td><td class="amt">${money(d.change ?? 0)}</td></tr>` : ''
  return rows || tendered ? `<div class="rule"></div><table>${rows}${tendered}</table>` : ''
}

const firsBlock = (d: ReceiptData) => [
  d.firsIrn ? `<div class="rule"></div><div class="c small">FIRS IRN: ${escape(d.firsIrn)}</div>` : '',
  d.qrCodeBase64 ? `<img class="qr" src="data:image/png;base64,${d.qrCodeBase64}" alt="">` : '',
].join('')

/**
 * Closing block. The person who recorded the sale is named here, directly above
 * "Powered by Audity", rather than in the header — it is provenance, and it
 * belongs with the sign-off.
 */
const signOff = (d: ReceiptData, thanks?: string) => `
  <div class="rule"></div>
  ${thanks ? `<div class="c small">${escape(thanks)}</div>` : ''}
  ${d.cashier ? `<div class="c small">${escape(d.cashierLabel || 'Served by')} ${escape(d.cashier)}</div>` : ''}
  <div class="c small">Powered by Audity</div>`

// ── Template bodies ──────────────────────────────────────────────────────────
function tplCompact(d: ReceiptData): string {
  return `
  ${logoImg(d, 'sm')}
  <div class="c b lg">${escape(d.merchant)}</div>
  ${addressBlock(d)}
  <div class="c small">${escape(d.invoiceNumber)} · ${escape(d.date)}</div>
  <div class="rule"></div>
  ${leaderLines(d)}
  <div class="rule"></div>
  ${totalsBlock(d)}
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  ${signOff(d)}`
}

function tplDetailed(d: ReceiptData): string {
  const idLine = [
    d.rcNumber ? `RC ${escape(d.rcNumber)}` : '',
    d.tin ? `TIN ${escape(d.tin)}` : '',
  ].filter(Boolean).join(' · ')
  return `
  ${logoImg(d, 'sm')}
  <div class="c b lg">${escape(d.merchant)}</div>
  ${idLine ? `<div class="c small">${idLine}</div>` : ''}
  ${addressBlock(d)}
  ${d.phone ? `<div class="c small">${escape(d.phone)}</div>` : ''}
  <div class="solid"></div>
  <table>
    <tr><td>Receipt</td><td class="amt b">${escape(d.invoiceNumber)}</td></tr>
    <tr><td>Date</td><td class="amt">${escape(d.date)}</td></tr>
    ${d.customer ? `<tr><td>Customer</td><td class="amt">${escape(d.customer)}</td></tr>` : ''}
    ${d.customerTin ? `<tr><td>Customer TIN</td><td class="amt">${escape(d.customerTin)}</td></tr>` : ''}
  </table>
  <div class="solid"></div>
  <table>
    <tr class="hdr"><th class="w4">Item</th><th class="amt">Qty</th><th class="amt">Price</th><th class="amt">Total</th></tr>
    ${columnLines(d)}
  </table>
  <div class="solid"></div>
  ${totalsBlock(d)}
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  <div class="small sig">RECEIVED BY</div>
  <div class="sigline"></div>
  ${signOff(d)}`
}

function tplBranded(d: ReceiptData): string {
  return `
  ${logoImg(d, 'lg')}
  <div class="c b lg">${escape(d.merchant)}</div>
  ${addressBlock(d)}
  ${contactBlock(d)}
  ${d.website ? `<div class="c small">${escape(d.website)}</div>` : ''}
  <div class="thick"></div>
  <table>
    <tr><td>Receipt</td><td class="amt b">${escape(d.invoiceNumber)}</td></tr>
    <tr><td>Date</td><td class="amt">${escape(d.date)}</td></tr>
    ${d.customer ? `<tr><td>Customer</td><td class="amt">${escape(d.customer)}</td></tr>` : ''}
  </table>
  <div class="rule"></div>
  <table>
    <tr class="hdr"><th>Item</th><th class="amt">Price</th><th class="amt">Total</th></tr>
    ${stackedLines(d)}
  </table>
  <div class="rule"></div>
  <table>
    <tr><td>Subtotal</td><td class="amt">${money(d.subtotal)}</td></tr>
    ${Number(d.discount || 0) ? `<tr><td>Discount</td><td class="amt">-${money(d.discount!)}</td></tr>` : ''}
    ${Number(d.tax || 0) ? `<tr><td>VAT</td><td class="amt">${money(d.tax!)}</td></tr>` : ''}
  </table>
  <div class="thick"></div>
  <table><tr class="tot"><td>TOTAL</td><td class="amt">${money(d.total)}</td></tr></table>
  <div class="thick"></div>
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  ${d.footerNote ? `<div class="c small note">${escape(d.footerNote)}</div>` : ''}
  ${signOff(d, 'Thank you for your patronage')}`
}

function tplClassicCash(d: ReceiptData): string {
  return `
  ${logoImg(d, 'sm')}
  <div class="c b lg sp">CASH RECEIPT</div>
  <div class="rule"></div>
  <table>
    <tr><td>Shop</td><td class="amt">${escape(d.merchant)}</td></tr>
    <tr><td>Date</td><td class="amt">${escape(d.date)}</td></tr>
    <tr><td>Receipt</td><td class="amt">${escape(d.invoiceNumber)}</td></tr>
    ${d.customer ? `<tr><td>Customer</td><td class="amt">${escape(d.customer)}</td></tr>` : ''}
  </table>
  ${addressLines(d.address).length ? `<div class="rule"></div>${addressBlock(d)}` : ''}
  <div class="rule"></div>
  <table>
    <tr class="hdr"><th>Item</th><th class="amt">Price</th><th class="amt">Total</th></tr>
    ${stackedLines(d)}
  </table>
  <div class="rule"></div>
  ${totalsBlock(d, 'Total')}
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  ${signOff(d, 'THANK YOU FOR SHOPPING!')}`
}

function tplShopBarcode(d: ReceiptData): string {
  const bc = code128Svg(d.invoiceNumber)
  return `
  ${logoImg(d, 'sm')}
  <div class="c b lg">${escape(d.merchant)}</div>
  <div class="rule"></div>
  <table>
    <tr><td>Receipt :</td><td class="amt">${escape(d.invoiceNumber)}</td></tr>
    <tr><td>Date :</td><td class="amt">${escape(d.date)}</td></tr>
  </table>
  ${addressBlock(d)}
  ${d.customer ? `<div class="small">Client : ${escape(d.customer)}</div>` : ''}
  <div class="rule"></div>
  ${leaderLines(d)}
  <div class="rule"></div>
  <div class="lead"><span>Subtotal</span><span class="fill"></span><span class="amt">${money(d.subtotal)}</span></div>
  ${Number(d.discount || 0) ? `<div class="lead"><span>Discount</span><span class="fill"></span><span class="amt">-${money(d.discount!)}</span></div>` : ''}
  ${Number(d.tax || 0) ? `<div class="lead"><span>VAT</span><span class="fill"></span><span class="amt">${money(d.tax!)}</span></div>` : ''}
  <div class="lead b tl"><span>TOTAL</span><span class="fill"></span><span class="amt">${money(d.total)}</span></div>
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  ${bc ? `${bc}<div class="c small">${escape(d.invoiceNumber)}</div>` : ''}
  ${signOff(d, 'THANK YOU FOR SHOPPING!')}`
}

function tplStayFolio(d: ReceiptData): string {
  const rows = d.lines.map((l) => `
    <tr>
      <td class="nm4">${escape(l.date || '')}</td>
      <td>${escape(l.ref || '')}</td>
      <td class="amt">${money(l.line_total)}</td>
    </tr>
    <tr><td class="mod" colspan="3">${escape(l.name)}</td></tr>`).join('')
  return `
  ${logoImg(d, 'sm')}
  <div class="c b lg">${escape(d.merchant)}</div>
  ${addressBlock(d)}
  ${d.rcNumber ? `<div class="c small">RC ${escape(d.rcNumber)}</div>` : ''}
  <div class="rule"></div>
  <table>
    <tr><td>Folio</td><td class="amt b">${escape(d.invoiceNumber)}</td></tr>
    <tr><td>Date</td><td class="amt">${escape(d.date)}</td></tr>
    ${d.customer ? `<tr><td>Guest</td><td class="amt">${escape(d.customer)}</td></tr>` : ''}
  </table>
  <div class="rule"></div>
  <table>
    <tr class="hdr"><th>Date</th><th>Ref</th><th class="amt">Total</th></tr>
    ${rows}
  </table>
  <div class="rule"></div>
  <div class="stars">*******************************</div>
  ${totalsBlock(d)}
  <div class="stars">*******************************</div>
  ${paymentsBlock(d)}
  ${firsBlock(d)}
  ${signOff(d, 'Thank you for your stay')}`
}

const BODIES: Record<ReceiptTemplate, (d: ReceiptData) => string> = {
  compact: tplCompact,
  detailed: tplDetailed,
  branded: tplBranded,
  classic_cash: tplClassicCash,
  shop_barcode: tplShopBarcode,
  stay_folio: tplStayFolio,
}

/** Build the 80mm receipt markup. Exported so it can be unit-tested. */
export function buildReceiptHtml(d: ReceiptData): string {
  const body = (BODIES[d.template as ReceiptTemplate] ?? tplCompact)(d)

  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${escape(d.invoiceNumber)}</title>
<style>
  /* 80mm roll. Margins are the printer's business, not ours. */
  @page { size: 80mm auto; margin: 0; }
  * { box-sizing: border-box; }
  body {
    width: 80mm; margin: 0; padding: 4mm 3mm;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px; line-height: 1.35; color: #000; background: #fff;
  }
  .c { text-align: center; }
  .b { font-weight: 700; }
  .lg { font-size: 14px; }
  .sp { letter-spacing: .1em; }
  .rule { border-top: 1px dashed #000; margin: 5px 0; }
  .solid { border-top: 1px solid #000; margin: 5px 0; }
  .thick { border-top: 2px solid #000; margin: 5px 0; }
  table { width: 100%; border-collapse: collapse; }
  td, th { padding: 0; vertical-align: top; text-align: left; font-weight: 400; }
  .amt { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .qty { color: #333; padding-left: 3mm; }
  .mod { color: #333; font-size: 10px; padding-left: 3mm; font-style: italic; }
  .nm { padding-top: 2px; }
  .nm4 { padding-top: 2px; width: 36%; word-break: break-word; }
  .hdr th {
    font-size: 9px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; padding-bottom: 2px;
  }
  .hdr th.w4 { width: 36%; }
  .tot td { font-size: 13px; font-weight: 700; padding-top: 3px; }
  .small { font-size: 9.5px; }
  .ind { padding-left: 3mm; color: #333; }
  .note { margin-top: 4px; }
  .stars { font-size: 9px; overflow: hidden; white-space: nowrap; }
  .lead { display: flex; align-items: baseline; gap: 3px; }
  .lead .fill { flex: 1; border-bottom: 1px dotted #000; transform: translateY(-3px); }
  .lead.tl { font-size: 13px; }
  .sig { margin-top: 14px; }
  .sigline { border-top: 1px solid #000; margin-top: 16px; }
  img.logo { display: block; margin: 0 auto 4px; max-width: 100%; }
  img.logo.sm { width: 34px; }
  img.logo.lg { width: 62px; }
  img.qr { width: 26mm; height: 26mm; margin: 4px auto 0; display: block; }
  svg.bc { display: block; width: 78%; height: 34px; margin: 8px auto 2px; }
</style></head>
<body>${body}</body></html>`
}

/**
 * Send a receipt to the printer.
 *
 * Prints from a hidden iframe rather than a popup window: popups are blocked by
 * default in the desktop shell and on Android, and a blocked popup looks to the
 * cashier like the printer simply failed.
 *
 * The logo is converted to mono and inlined as a data URI *before* the iframe
 * is written, so the print dialog can never snapshot the page mid-download and
 * emit a receipt with a blank space where the logo should be.
 */
export async function printReceipt(d: ReceiptData): Promise<void> {
  let logoDataUrl: string | null = null
  if (d.logoDataUrl) {
    try { logoDataUrl = await toMonoDataUrl(d.logoDataUrl) } catch { logoDataUrl = null }
  }

  const html = buildReceiptHtml({ ...d, logoDataUrl })
  const frame = document.createElement('iframe')
  frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;'
  document.body.appendChild(frame)

  const cleanup = () => { if (frame.parentNode) frame.parentNode.removeChild(frame) }

  frame.onload = () => {
    try {
      frame.contentWindow?.focus()
      frame.contentWindow?.print()
    } finally {
      // Give the print dialog time to take its snapshot before we tear the
      // frame down — removing it immediately prints a blank page on WebKit.
      window.setTimeout(cleanup, 1500)
    }
  }

  const doc = frame.contentDocument
  if (!doc) { cleanup(); return }
  doc.open(); doc.write(html); doc.close()
}
