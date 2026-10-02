import { describe, expect, it } from 'vitest'
import { productTaxRate, roundMoney, saleLine, saleTotals } from '@/lib/saleMath'

// Expected figures are the ones the server saved on staging for the same inputs.

describe('roundMoney', () => {
  it('rounds half up like the server', () => {
    expect(roundMoney(92.5725)).toBe(92.57)
    expect(roundMoney(0.125)).toBe(0.13)
    expect(roundMoney(1.005)).toBe(1.01) // float artefact: 1.005 * 100 = 100.4999…
    expect(roundMoney(-1.005)).toBe(-1.01)
    expect(roundMoney(0)).toBe(0)
  })
})

describe('saleLine', () => {
  it('exclusive VAT goes on top, after the discount', () => {
    // 3 x 1,500 less 10%, VAT 7.5% -> INV-2DFB-000001
    expect(saleLine({ unitPrice: 1500, quantity: 3, discountPercent: 10, taxRate: 7.5 }))
      .toEqual({ subtotal: 4500, discount: 450, tax: 303.75, lineTotal: 4353.75 })
  })

  it('rounds each step to the kobo', () => {
    // 7 x 333.33 less 12.5%, VAT 7.5% -> the awkward cash sale
    expect(saleLine({ unitPrice: 333.33, quantity: 7, discountPercent: 12.5, taxRate: 7.5 }))
      .toEqual({ subtotal: 2333.31, discount: 291.66, tax: 153.12, lineTotal: 2194.77 })
  })

  it('inclusive VAT is backed out of the price, not added', () => {
    // 2 x 1,075 incl. 7.5% less 10% -> total 1,935, VAT 135
    expect(saleLine({ unitPrice: 1075, quantity: 2, discountPercent: 10, taxRate: 7.5, inclusive: true }))
      .toEqual({ subtotal: 2150, discount: 215, tax: 135, lineTotal: 1935 })
  })

  it('an untaxed line has no VAT whether or not it is marked inclusive', () => {
    expect(saleLine({ unitPrice: 500, quantity: 1, inclusive: true }).lineTotal).toBe(500)
    expect(saleLine({ unitPrice: 500, quantity: 1 }).tax).toBe(0)
  })
})

describe('saleTotals', () => {
  it('sums rounded lines, so the total matches the saved invoice', () => {
    // Three 1,234.30 lines at 7.5%: the server saves 3 x 92.57 = 277.71 VAT,
    // 3,980.61 total. Summing unrounded floats gave 277.72 / 3,980.62.
    const line = { unitPrice: 1234.3, quantity: 1, taxRate: 7.5 }
    const t = saleTotals([line, line, line])
    expect(t.tax).toBe(277.71)
    expect(t.total).toBe(3980.61)
  })

  it('adds shipping once, after the lines', () => {
    expect(saleTotals([{ unitPrice: 1000, quantity: 1, taxRate: 7.5 }], 500).total).toBe(1575)
  })
})

describe('productTaxRate', () => {
  const rates = { vat: 7.5 }
  it('uses the tax class rate only when the product is taxable', () => {
    expect(productTaxRate({ is_taxable: true, tax_class: 'vat' }, rates)).toBe(7.5)
    expect(productTaxRate({ is_taxable: false, tax_class: 'vat' }, rates)).toBe(0)
    expect(productTaxRate({ is_taxable: true, tax_class: null }, rates)).toBe(0)
  })
})
