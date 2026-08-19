import { describe, it, expect } from 'vitest'
import {
  buildReceiptHtml,
  code128Svg,
  RECEIPT_TEMPLATES,
  type ReceiptData,
  type ReceiptTemplate,
} from '@/lib/receipt'

const base: ReceiptData = {
  merchant: 'McEva International',
  address: '14 Admiralty Way, Lekki\nLagos',
  phone: '0803 000 0000',
  tin: '12345678-0001',
  invoiceNumber: 'INV-8354-000008',
  date: '18/08/2026',
  cashier: 'Ada Okafor',
  customer: 'I K C Uzoukwu Global Concepts',
  lines: [
    { name: 'DON JULIO 1942', qty: 100, unit_price: 950000, line_total: 95000000 },
    { name: 'HENNESSY VS 750ML', qty: 12, unit_price: 85000, line_total: 1020000 },
  ],
  subtotal: 96020000,
  tax: 7201500,
  total: 103221500,
}

describe('receipt money formatting', () => {
  it('drops a trailing .00 — a whole-naira total prints without decimals', () => {
    const html = buildReceiptHtml(base)
    expect(html).toContain('95,000,000')
    expect(html).not.toContain('95,000,000.00')
    expect(html).toContain('103,221,500')
    expect(html).not.toContain('103,221,500.00')
  })

  it('keeps real kobo, and pads it to two places', () => {
    const html = buildReceiptHtml({
      ...base,
      lines: [{ name: 'SACHET', qty: 3, unit_price: 411.5, line_total: 1234.5 }],
      subtotal: 1234.5, tax: 0, total: 1234.56,
    })
    expect(html).toContain('1,234.50')
    expect(html).toContain('1,234.56')
  })

  it('never pads a whole quantity, but keeps a fractional one', () => {
    const html = buildReceiptHtml({
      ...base,
      lines: [
        { name: 'CRATE', qty: 100, unit_price: 1, line_total: 100 },
        { name: 'RICE (KG)', qty: 1.5, unit_price: 2, line_total: 3 },
      ],
    })
    expect(html).toContain('100 ×')
    expect(html).not.toContain('100.00 ×')
    expect(html).toContain('1.5 ×')
  })
})

describe('receipt sign-off', () => {
  it('names the user who recorded the sale directly above Powered by Audity', () => {
    const html = buildReceiptHtml(base)
    const servedAt = html.indexOf('Served by Ada Okafor')
    const poweredAt = html.indexOf('Powered by Audity')
    expect(servedAt).toBeGreaterThan(-1)
    expect(poweredAt).toBeGreaterThan(servedAt)
  })

  it('does not repeat the operator in the header', () => {
    // Exactly one mention, and it is the sign-off.
    const html = buildReceiptHtml(base)
    expect(html.match(/Ada Okafor/g)).toHaveLength(1)
  })

  it('uses the caller-supplied label, so an invoice reads "Raised by"', () => {
    const html = buildReceiptHtml({ ...base, cashierLabel: 'Raised by' })
    expect(html).toContain('Raised by Ada Okafor')
    expect(html).not.toContain('Served by')
  })

  it('omits the line entirely when no user is known', () => {
    const html = buildReceiptHtml({ ...base, cashier: undefined })
    expect(html).not.toContain('Served by')
    expect(html).toContain('Powered by Audity')
  })
})

describe('receipt content', () => {
  it('labels the columns Price and Total, never Description or Cost', () => {
    const html = buildReceiptHtml({ ...base, template: 'detailed' })
    expect(html).toContain('>Price<')
    expect(html).toContain('>Total<')
    expect(html).not.toContain('Description')
    expect(html).not.toContain('>Cost<')
  })

  it('prints the profile address, one line per entered line', () => {
    const html = buildReceiptHtml(base)
    expect(html).toContain('14 Admiralty Way, Lekki')
    expect(html).toContain('Lagos')
  })

  it('carries no e-mail capture footer on any template', () => {
    for (const t of RECEIPT_TEMPLATES) {
      const html = buildReceiptHtml({ ...base, template: t.value })
      expect(html.toLowerCase(), t.value).not.toContain('mailing list')
      expect(html.toLowerCase(), t.value).not.toContain('e-mail')
    }
  })

  it('escapes merchant-controlled text rather than injecting it as markup', () => {
    const html = buildReceiptHtml({ ...base, merchant: '<script>alert(1)</script>' })
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('renders every advertised template without throwing', () => {
    for (const t of RECEIPT_TEMPLATES) {
      const html = buildReceiptHtml({ ...base, template: t.value })
      expect(html, t.value).toContain('103,221,500')
      expect(html, t.value).toContain('McEva International')
    }
  })

  it('falls back to compact for an unknown template rather than rendering nothing', () => {
    const html = buildReceiptHtml({ ...base, template: 'nope' as ReceiptTemplate })
    expect(html).toContain('103,221,500')
  })
})

describe('code 128 barcode', () => {
  it('encodes an invoice number as bars', () => {
    const svg = code128Svg('INV-8354-000008')
    expect(svg).toContain('<svg')
    expect(svg).toContain('<rect')
  })

  it('emits nothing rather than an unscannable symbol for out-of-range input', () => {
    // Outside printable ASCII, which Code 128B cannot represent.
    expect(code128Svg('INV—8354')).toBe('')
    expect(code128Svg('')).toBe('')
  })

  it('produces a different symbol for a different reference', () => {
    expect(code128Svg('INV-0001')).not.toBe(code128Svg('INV-0002'))
  })

  it('only appears on the barcode template', () => {
    expect(buildReceiptHtml({ ...base, template: 'shop_barcode' })).toContain('class="bc"')
    expect(buildReceiptHtml({ ...base, template: 'compact' })).not.toContain('class="bc"')
  })
})
