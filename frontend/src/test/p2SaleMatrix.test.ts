/**
 * Design phase 2: the screen's arithmetic must equal the server's, case by case.
 * These are the SAME cases as backend/apps/sales/test_p2_sale_matrix.py, with the
 * same hand-worked answers (VAT 7.5%), so a drift between screen and server shows
 * up as one test going red on one side only.
 */
import { describe, it, expect } from 'vitest'
import { saleLine, saleTotals, roundMoney } from '../lib/saleMath'

const VAT = 7.5

describe('screen arithmetic vs hand-worked server values', () => {
  it('3 x 1000, 10% off, VAT on top: 3000 / 300 / 202.50 / 2902.50', () => {
    const t = saleTotals([{ unitPrice: 1000, quantity: 3, discountPercent: 10, taxRate: VAT }])
    expect(t).toMatchObject({ subtotal: 3000, discount: 300, tax: 202.5, total: 2902.5 })
  })
  it('1 x 1000 + VAT = 1075', () => {
    expect(saleTotals([{ unitPrice: 1000, quantity: 1, taxRate: VAT }]).total).toBe(1075)
  })
  it('VAT-inclusive 1075 stays 1075 and carries 75 of VAT', () => {
    const l = saleLine({ unitPrice: 1075, quantity: 1, taxRate: VAT, inclusive: true })
    expect(l).toMatchObject({ tax: 75, lineTotal: 1075 })
  })
  it('delivery 500 is added after VAT and is not taxed: 1575', () => {
    const t = saleTotals([{ unitPrice: 1000, quantity: 1, taxRate: VAT }], 500)
    expect(t.tax).toBe(75)
    expect(t.total).toBe(1575)
  })
  it('mixed exclusive 1000 + inclusive 1075: VAT 150, total 2150', () => {
    const t = saleTotals([
      { unitPrice: 1000, quantity: 1, taxRate: VAT },
      { unitPrice: 1075, quantity: 1, taxRate: VAT, inclusive: true },
    ])
    expect(t.tax).toBe(150)
    expect(t.total).toBe(2150)
  })
  describe('kobo rounding (half up)', () => {
    it('3 x 33.33: VAT 7.49925 -> 7.50, total 107.49', () => {
      const t = saleTotals([{ unitPrice: 33.33, quantity: 3, taxRate: VAT }])
      expect(t).toMatchObject({ subtotal: 99.99, tax: 7.5, total: 107.49 })
    })
    it('0.10: VAT 0.0075 -> 0.01, total 0.11', () => {
      expect(saleTotals([{ unitPrice: 0.1, quantity: 1, taxRate: VAT }])).toMatchObject({ tax: 0.01, total: 0.11 })
    })
    it('0.06: VAT 0.0045 -> 0.00, total 0.06', () => {
      expect(saleTotals([{ unitPrice: 0.06, quantity: 1, taxRate: VAT }])).toMatchObject({ tax: 0, total: 0.06 })
    })
    it('two lines of 0.06 round line by line: VAT 0.00, not 0.01', () => {
      const l = { unitPrice: 0.06, quantity: 1, taxRate: VAT }
      expect(saleTotals([l, l])).toMatchObject({ tax: 0, total: 0.12 })
    })
    it('1.005 rounds to 1.01 (no float artefact)', () => {
      expect(roundMoney(1.005)).toBe(1.01)
    })
  })
  describe('zero, negative and extreme amounts', () => {
    it('100% discount gives 0 with no VAT', () => {
      expect(saleTotals([{ unitPrice: 1000, quantity: 1, discountPercent: 100, taxRate: VAT }]))
        .toMatchObject({ discount: 1000, tax: 0, total: 0 })
    })
    it('empty basket is exactly 0, never NaN or -0', () => {
      const t = saleTotals([])
      expect(t.total).toBe(0)
      expect(Object.is(t.total, -0)).toBe(false)
    })
    it('NaN-ish inputs do not poison the total', () => {
      const t = saleTotals([{ unitPrice: NaN, quantity: 1, taxRate: VAT }])
      expect(Number.isFinite(t.total)).toBe(true)
    })
    it('a big sale stays exact to the kobo: 9,999,999.99 + VAT 750,000 (rounded)', () => {
      // 9999999.99 x 7.5% = 749999.99925 -> 750000.00 ; total 10749999.99
      const t = saleTotals([{ unitPrice: 9999999.99, quantity: 1, taxRate: VAT }])
      expect(t).toMatchObject({ tax: 750000, total: 10749999.99 })
    })
    it('negative shipping (a delivery credit) lowers the total by exactly that', () => {
      expect(saleTotals([{ unitPrice: 1000, quantity: 1 }], -100).total).toBe(900)
    })
  })
})

// REPRODUCER (found by the design-phase-2 merge gate on a Postgres stack, 2026-11-20).
// The server spreads "Total adjustment" over the lines BEFORE VAT (SaleService._allocate_adjustment,
// apps/sales/services.py) and the senior accountant's rule says the same: an adjustment lowers
// (or raises) the price VAT is charged on. saleMath.ts adds it AFTER VAT instead, so the page
// shows a different total than the server saves and the "Total differs from the screen" pop-up fires.
// Hand work, lines 10,000 + 5,000, adjustment -1,500, VAT 7.5%:
//   net 15,000 - 1,500 = 13,500 ; VAT 13,500 x 7.5% = 1,012.50 ; total 14,512.50
// The page shows 14,625.00 today (15,000 + 1,125 VAT - 1,500).
// `it.fails` keeps the suite green while the bug is open and turns RED the day it is fixed;
// delete the `.fails` then.
describe('total adjustment is taxed like a discount (server rule)', () => {
  const lines = [
    { unitPrice: 10000, quantity: 1, taxRate: VAT },
    { unitPrice: 5000, quantity: 1, taxRate: VAT },
  ]
  it.fails('-1,500 on 10,000 + 5,000: VAT 1,012.50, total 14,512.50', () => {
    const t = saleTotals(lines, 0, -1500)
    expect(t.tax).toBe(1012.5)
    expect(t.total).toBe(14512.5)
  })
  it.fails('-100 on 1,000: VAT 67.50, total 967.50', () => {
    const t = saleTotals([{ unitPrice: 1000, quantity: 1, taxRate: VAT }], 0, -100)
    expect(t.total).toBe(967.5)
  })
  it.fails('+100 on 1,000: VAT 82.50, total 1,182.50', () => {
    const t = saleTotals([{ unitPrice: 1000, quantity: 1, taxRate: VAT }], 0, 100)
    expect(t.total).toBe(1182.5)
  })
})
