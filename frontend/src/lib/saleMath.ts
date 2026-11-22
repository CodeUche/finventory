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

/** One line's money. `adjustment` is this line's share of a whole-invoice adjustment (see
 *  allocateAdjustment): it is added to the after-discount value BEFORE VAT, so the VAT moves with it,
 *  exactly like the server's _commit_line. With no adjustment nothing changes. */
export function saleLine(l: SaleLineInput, adjustment = 0): SaleLineAmounts {
  const rate = l.taxRate ?? 0
  const subtotal = roundMoney((l.quantity || 0) * (l.unitPrice || 0))
  const discount = roundMoney((subtotal * (l.discountPercent || 0)) / 100)
  const after = roundMoney(subtotal - discount + adjustment)
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

/** Half-up to the kobo for a ratio of two whole-kobo numbers, away from zero on a tie, with no float error
 *  (the server's Decimal ROUND_HALF_UP). */
function ratioKobo(numer: bigint, denom: bigint): bigint {
  const neg = (numer < 0n) !== (denom < 0n)
  const n = numer < 0n ? -numer : numer
  const d = denom < 0n ? -denom : denom
  const q = (2n * n + d) / (2n * d)
  return neg ? -q : q
}
const toKobo = (n: number): bigint => BigInt(Math.round(n * 100))

export interface AdjustmentSplit {
  /** Each line's share, in the order of the lines. Zeros when the adjustment is refused. */
  shares: number[]
  /** Why the server would refuse it, or null. */
  error: 'no-value' | 'bigger-than-invoice' | 'line-below-zero' | null
}

/**
 * Spread a signed whole-invoice adjustment over the lines in proportion to each line's after-discount value
 * (before VAT). The last line takes the rounding remainder. Same steps and refusals as the server's
 * SaleService._allocate_adjustment, so the figure on screen is the figure saved.
 */
export function allocateAdjustment(afters: number[], adjustment: number): AdjustmentSplit {
  const zeros = afters.map(() => 0)
  const adjK = toKobo(roundMoney(adjustment || 0))
  if (adjK === 0n || afters.length === 0) return { shares: zeros, error: null }
  const afterK = afters.map(toKobo)
  const baseK = afterK.reduce((a, b) => a + b, 0n)
  if (baseK <= 0n) return { shares: zeros, error: 'no-value' }
  if (adjK < 0n && -adjK > baseK) return { shares: zeros, error: 'bigger-than-invoice' }
  const sharesK: bigint[] = []
  let running = 0n
  afterK.forEach((a, i) => {
    const share = i === afterK.length - 1 ? adjK - running : ratioKobo(adjK * a, baseK)
    running += share
    sharesK.push(share)
  })
  if (sharesK.some((sh, i) => afterK[i] + sh < 0n)) return { shares: zeros, error: 'line-below-zero' }
  return { shares: sharesK.map((k) => Number(k) / 100), error: null }
}

export interface SaleBreakdown extends SaleTotals {
  /** Per line, with its share of the adjustment already in (VAT included). */
  lines: SaleLineAmounts[]
  adjustmentError: AdjustmentSplit['error']
}

/** Every figure a sale screen shows, line by line, equal to what the server saves. `adjustment` is the
 *  signed "Total adjustment"; `shipping` is outside VAT (the delivery-VAT switch is off). */
export function saleBreakdown(inputs: SaleLineInput[], shipping = 0, adjustment = 0): SaleBreakdown {
  const plain = inputs.map((l) => saleLine(l))
  const split = allocateAdjustment(plain.map((a) => roundMoney(a.subtotal - a.discount)), adjustment)
  const lines = inputs.map((l, i) => saleLine(l, split.shares[i]))
  const sum = lines.reduce(
    (acc, l) => ({
      subtotal: acc.subtotal + l.subtotal, discount: acc.discount + l.discount,
      tax: acc.tax + l.tax, lineTotal: acc.lineTotal + l.lineTotal,
    }),
    { subtotal: 0, discount: 0, tax: 0, lineTotal: 0 },
  )
  return {
    subtotal: roundMoney(sum.subtotal),
    discount: roundMoney(sum.discount),
    tax: roundMoney(sum.tax),
    lineTotal: roundMoney(sum.lineTotal),
    total: roundMoney(sum.lineTotal + (shipping || 0)),
    lines,
    adjustmentError: split.error,
  }
}

/** The totals of a sale. `adjustment` is spread over the lines BEFORE VAT (see allocateAdjustment), so VAT
 *  moves with it. */
export function saleTotals(lines: SaleLineInput[], shipping = 0, adjustment = 0): SaleTotals {
  const { subtotal, discount, tax, lineTotal, total } = saleBreakdown(lines, shipping, adjustment)
  return { subtotal, discount, tax, lineTotal, total }
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

/** The part of the VAT that is already inside the prices (VAT-inclusive lines). */
export function saleTaxIncluded(lines: SaleLineInput[]): number {
  return roundMoney(
    lines.reduce((a, l) => a + (l.inclusive && (l.taxRate ?? 0) > 0 ? saleLine(l).tax : 0), 0),
  )
}
