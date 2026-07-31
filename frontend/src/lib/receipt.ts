/**
 * Thermal receipt printing.
 *
 * Rather than talk to a printer directly — which needs a driver per model and
 * does not work at all from a browser — we render an 80mm-wide page and hand it
 * to the operating system's print dialog. Every thermal printer in a Nigerian
 * shop is installed as a normal Windows/Android printer, so this reaches all of
 * them, including the printer built into a POS terminal.
 */

export interface ReceiptLine {
  name: string
  qty: number | string
  unit_price: number | string
  line_total: number | string
}

export interface ReceiptPayment {
  method: string
  amount: number | string
}

export interface ReceiptData {
  merchant: string
  address?: string
  phone?: string
  tin?: string
  invoiceNumber: string
  date: string
  cashier?: string
  customer?: string
  lines: ReceiptLine[]
  subtotal: number | string
  tax?: number | string
  discount?: number | string
  total: number | string
  payments?: ReceiptPayment[]
  amountTendered?: number | string
  change?: number | string
  footer?: string
  /** FIRS invoice reference number, printed when the sale was cleared. */
  firsIrn?: string
  qrCodeBase64?: string
}

const money = (v: number | string) =>
  Number(v || 0).toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const escape = (s: string) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string
  ))

const TENDER_LABEL: Record<string, string> = {
  cash: 'Cash',
  pos: 'Card',
  card: 'Card',
  bank_transfer: 'Transfer',
  cheque: 'Cheque',
  credit_applied: 'On account',
}

/** Build the 80mm receipt markup. Exported so it can be unit-tested. */
export function buildReceiptHtml(d: ReceiptData): string {
  const rows = d.lines.map((l) => `
    <tr>
      <td colspan="2" class="nm">${escape(l.name)}</td>
    </tr>
    <tr>
      <td class="qty">${money(l.qty)} × ${money(l.unit_price)}</td>
      <td class="amt">${money(l.line_total)}</td>
    </tr>`).join('')

  const payments = (d.payments ?? []).map((p) => `
    <tr><td>${escape(TENDER_LABEL[p.method] ?? p.method)}</td>
        <td class="amt">${money(p.amount)}</td></tr>`).join('')

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
  .rule { border-top: 1px dashed #000; margin: 5px 0; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 0; vertical-align: top; }
  .amt { text-align: right; white-space: nowrap; }
  .qty { color: #333; padding-left: 3mm; }
  .nm { padding-top: 2px; }
  .tot td { font-size: 13px; font-weight: 700; padding-top: 3px; }
  .small { font-size: 9.5px; }
  img.qr { width: 26mm; height: 26mm; margin: 4px auto 0; display: block; }
</style></head>
<body>
  <div class="c b lg">${escape(d.merchant)}</div>
  ${d.address ? `<div class="c small">${escape(d.address)}</div>` : ''}
  ${d.phone ? `<div class="c small">${escape(d.phone)}</div>` : ''}
  ${d.tin ? `<div class="c small">TIN: ${escape(d.tin)}</div>` : ''}

  <div class="rule"></div>
  <table>
    <tr><td>Receipt</td><td class="amt b">${escape(d.invoiceNumber)}</td></tr>
    <tr><td>Date</td><td class="amt">${escape(d.date)}</td></tr>
    ${d.cashier ? `<tr><td>Served by</td><td class="amt">${escape(d.cashier)}</td></tr>` : ''}
    ${d.customer ? `<tr><td>Customer</td><td class="amt">${escape(d.customer)}</td></tr>` : ''}
  </table>

  <div class="rule"></div>
  <table>${rows}</table>
  <div class="rule"></div>

  <table>
    <tr><td>Subtotal</td><td class="amt">${money(d.subtotal)}</td></tr>
    ${Number(d.discount || 0) ? `<tr><td>Discount</td><td class="amt">-${money(d.discount!)}</td></tr>` : ''}
    ${Number(d.tax || 0) ? `<tr><td>VAT</td><td class="amt">${money(d.tax!)}</td></tr>` : ''}
    <tr class="tot"><td>TOTAL</td><td class="amt">${money(d.total)}</td></tr>
  </table>

  ${payments ? `<div class="rule"></div><table>${payments}</table>` : ''}
  ${Number(d.amountTendered || 0) ? `
    <table>
      <tr><td>Tendered</td><td class="amt">${money(d.amountTendered!)}</td></tr>
      <tr><td>Change</td><td class="amt">${money(d.change ?? 0)}</td></tr>
    </table>` : ''}

  ${d.firsIrn ? `<div class="rule"></div><div class="c small">FIRS IRN: ${escape(d.firsIrn)}</div>` : ''}
  ${d.qrCodeBase64 ? `<img class="qr" src="data:image/png;base64,${d.qrCodeBase64}" alt="">` : ''}

  <div class="rule"></div>
  <div class="c small">${escape(d.footer ?? 'Thank you for your patronage')}</div>
  <div class="c small">Powered by Audity</div>
</body></html>`
}

/**
 * Send a receipt to the printer.
 *
 * Prints from a hidden iframe rather than a popup window: popups are blocked by
 * default in the desktop shell and on Android, and a blocked popup looks to the
 * cashier like the printer simply failed.
 */
export function printReceipt(d: ReceiptData): void {
  const html = buildReceiptHtml(d)
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
