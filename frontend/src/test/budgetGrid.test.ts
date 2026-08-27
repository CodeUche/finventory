import { describe, it, expect } from 'vitest'
import {
  computeCopyForwardAmounts,
  applyCopyForward,
  sumBudgetedAmount,
  buildBulkLinesPayload,
  type GridRow,
} from '@/lib/budgetGrid'

describe('computeCopyForwardAmounts', () => {
  it('copies the flat value with no adjustment across all remaining months', () => {
    const res = computeCopyForwardAmounts(1000, 0, 0)
    expect(res).toHaveLength(11) // Feb..Dec
    expect(res.every((v) => v === 1000)).toBe(true)
  })

  it('applies a positive % adjustment once (not compounding)', () => {
    const res = computeCopyForwardAmounts(1000, 6, 10) // from Jul, +10%
    expect(res).toHaveLength(5) // Aug..Dec
    expect(res.every((v) => v === 1100)).toBe(true)
  })

  it('applies a negative % adjustment', () => {
    const res = computeCopyForwardAmounts(1000, 5, -20)
    expect(res.every((v) => v === 800)).toBe(true)
  })

  it('rounds to 2dp', () => {
    const res = computeCopyForwardAmounts(333.33, 0, 10)
    expect(res[0]).toBeCloseTo(366.66, 2)
  })

  it('returns an empty array when copying from December (nothing left)', () => {
    expect(computeCopyForwardAmounts(1000, 11, 5)).toEqual([])
  })

  it('returns an empty array for a non-finite base amount', () => {
    expect(computeCopyForwardAmounts(NaN, 0, 0)).toEqual([])
  })

  it('treats an undefined percent as 0% (no change)', () => {
    const res = computeCopyForwardAmounts(500, 9)
    expect(res).toEqual([500, 500])
  })
})

describe('applyCopyForward', () => {
  it('fills months after the source index, leaves prior months untouched', () => {
    const months = ['100', '', '', '', '', '', '', '', '', '', '', '']
    const next = applyCopyForward(months, 0, 10)
    expect(next[0]).toBe('100') // source cell unchanged
    expect(next[1]).toBe('110')
    expect(next[11]).toBe('110')
  })

  it('does not mutate the original array', () => {
    const months = ['100', '', '', '', '', '', '', '', '', '', '', '']
    const copy = [...months]
    applyCopyForward(months, 0, 0)
    expect(months).toEqual(copy)
  })

  it('is a no-op when the source cell is empty', () => {
    const months = Array(12).fill('')
    const next = applyCopyForward(months, 3, 10)
    expect(next).toEqual(months)
  })
})

describe('sumBudgetedAmount', () => {
  it('sums string decimal amounts', () => {
    expect(sumBudgetedAmount([{ budgeted_amount: '100.50' }, { budgeted_amount: '49.50' }])).toBe(150)
  })

  it('ignores non-numeric entries instead of producing NaN', () => {
    expect(sumBudgetedAmount([{ budgeted_amount: '100' }, { budgeted_amount: 'garbage' }])).toBe(100)
  })

  it('returns 0 for an empty list', () => {
    expect(sumBudgetedAmount([])).toBe(0)
  })
})

describe('buildBulkLinesPayload', () => {
  it('skips rows with a blank category name', () => {
    const rows: GridRow[] = [
      { key: 'a', category_name: '  ', category_type: 'expense', account: '', months: ['100', ...Array(11).fill('')] },
    ]
    expect(buildBulkLinesPayload(rows)).toEqual([])
  })

  it('skips empty month cells rather than submitting them as 0', () => {
    const months = Array(12).fill('')
    months[0] = '5000'
    months[5] = '6000'
    const rows: GridRow[] = [{ key: 'a', category_name: 'Rent', category_type: 'expense', account: '', months }]
    const payload = buildBulkLinesPayload(rows)
    expect(payload).toHaveLength(2)
    expect(payload).toEqual(expect.arrayContaining([
      { category_name: 'Rent', category_type: 'expense', period_month: 1, budgeted_amount: 5000 },
      { category_name: 'Rent', category_type: 'expense', period_month: 6, budgeted_amount: 6000 },
    ]))
  })

  it('includes the account id only when set', () => {
    const months = Array(12).fill('')
    months[0] = '100'
    const withAccount: GridRow[] = [{ key: 'a', category_name: 'Rent', category_type: 'expense', account: 'acc-1', months }]
    const withoutAccount: GridRow[] = [{ key: 'b', category_name: 'Rent', category_type: 'expense', account: '', months }]
    expect(buildBulkLinesPayload(withAccount)[0].account).toBe('acc-1')
    expect(buildBulkLinesPayload(withoutAccount)[0]).not.toHaveProperty('account')
  })
})
