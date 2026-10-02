/**
 * Sale arithmetic — mirrors the server exactly, so the total a screen shows is
 * the total the invoice is saved with.
 *
 * The server (SaleService._process_line_item + create_sale in
 * apps/sales/services.py) works line by line in Decimal, rounding each step to
 * the kobo, half-up:
 *
 *   subtotal  = round(qty × unit price)
 *   discount  = round(subtotal × discount% / 100)
 *   after     = subtotal − discount
 *   exclusive : tax = round(after × rate / 100),          line total = after + tax
 *   inclusive : tax = round(after × rate / (100 + rate)), line total = after
 *   invoice total = Σ line totals + shipping
 *
 * Screens used to work in unrounded floats, or leave VAT out entirely: the New
 * Sale and Register totals had no VAT, so a cashier took the VAT-exclusive
 * amount and every taxed counter sale was saved part-paid with the VAT owed.
 */

/** Half-up to 2 places, like the server's round_money. The `e2` shift keeps
 *  binary float artefacts (1.005 × 100 = 100.4999…) from rounding the wrong way. */
export function roundMoney(n: number): number {
  if (!Number.isFinite(n) || Math.abs(n) < 1e-9) return 0
  const v = Number(n.toPrecision(15))
  const sign = v < 0 ? -1 : 1
  return sign * Number(Math.round(Number(`${Math.abs(v)}e2`)) + 'e-2')
}

export interface SaleLineInput {
  unitPrice: number
  quantity: number
  discountPercent?: number
  /** VAT rate in percent; 0 for an untaxed line. */
  taxRate?: number
  /** Price already contains the VAT (Product.tax_type === 'inclusive'). */
  inclusive?: boolean
}

export interface SaleLineAmounts {
  subtotal: number
  discount: number
  tax: number
  lineTotal: number
}

export function saleLine(l: SaleLineInput): SaleLineAmounts {
  const rate = l.taxRate ?? 0
  const subtotal = roundMoney((l.quantity || 0) * (l.unitPrice || 0))
  const discount = roundMoney((subtotal * (l.discountPercent || 0)) / 100)
  const after = roundMoney(subtotal - discount)
  if (l.inclusive && rate > 0) {
    return { subtotal, discount, tax: roundMoney((after * rate) / (100 + rate)), lineTotal: after }
  }
  const tax = roundMoney((after * rate) / 100)
  return { subtotal, discount, tax, lineTotal: roundMoney(after + tax) }
}

export interface SaleTotals extends SaleLineAmounts {
  /** Σ line totals + shipping — what the customer pays. */
  total: number
}

export function saleTotals(lines: SaleLineInput[], shipping = 0): SaleTotals {
  const sum = lines.map(saleLine).reduce(
    (acc, l) => ({
      subtotal: acc.subtotal + l.subtotal,
      discount: acc.discount + l.discount,
      tax: acc.tax + l.tax,
      lineTotal: acc.lineTotal + l.lineTotal,
    }),
    { subtotal: 0, discount: 0, tax: 0, lineTotal: 0 },
  )
  return {
    subtotal: roundMoney(sum.subtotal),
    discount: roundMoney(sum.discount),
    tax: roundMoney(sum.tax),
    lineTotal: roundMoney(sum.lineTotal),
    total: roundMoney(sum.lineTotal + (shipping || 0)),
  }
}

/** The VAT rate the server will apply to a product by default: its tax class's
 *  rate when it is taxable and has one, otherwise 0. */
export function productTaxRate(
  product: { is_taxable?: boolean; tax_class?: string | null },
  ratesByClass: Record<string, number>,
): number {
  if (!product.is_taxable || !product.tax_class) return 0
  return ratesByClass[product.tax_class] ?? 0
}
