import { describe, it, expect } from 'vitest'
import {
  computeCopyForwardAmounts,
  applyCopyForward,
  sumBudgetedAmount,
  buildBulkLinesPayload,
  computeFrequencyAmounts,
  applyFrequencyCopy,
  roundToNearest,
  sumRowMonths,
  sumColumnAcrossRows,
  computeSubtotals,
  type GridRow,
} from '@/lib/budgetGrid'
import type { Account } from '@/types'

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

describe('roundToNearest', () => {
  it('rounds to the nearest 100', () => {
    expect(roundToNearest(1234, 100)).toBe(1200)
    expect(roundToNearest(1250, 100)).toBe(1300) // .5 rounds up
  })

  it('rounds to the nearest 1000', () => {
    expect(roundToNearest(1499, 1000)).toBe(1000)
    expect(roundToNearest(1500, 1000)).toBe(2000)
  })

  it('rounds to the nearest 10', () => {
    expect(roundToNearest(1234, 10)).toBe(1230)
  })

  it('is a no-op when nearest is 0 or falsy', () => {
    expect(roundToNearest(1234, 0)).toBe(1234)
  })

  it('is a no-op for a non-finite value', () => {
    expect(roundToNearest(NaN, 100)).toBe(NaN)
  })
})

describe('computeFrequencyAmounts', () => {
  it('once — only the starting month itself gets a value', () => {
    const res = computeFrequencyAmounts(1000, 3, 'once')
    expect(res).toEqual([{ monthIndex: 3, value: 1000 }])
  })

  it('monthly — every month from the start through December, INCLUDING the start', () => {
    const res = computeFrequencyAmounts(500, 9, 'monthly') // start Oct
    expect(res).toEqual([
      { monthIndex: 9, value: 500 },
      { monthIndex: 10, value: 500 },
      { monthIndex: 11, value: 500 },
    ])
  })

  it('quarterly — only absolute quarter-end months (Mar/Jun/Sep/Dec), filtered to the start onward', () => {
    const res = computeFrequencyAmounts(1000, 0, 'quarterly') // start Jan -> all 4 quarter-ends remain
    expect(res.map((r) => r.monthIndex)).toEqual([2, 5, 8, 11])
    expect(res.every((r) => r.value === 1000)).toBe(true)
  })

  it('quarterly starting mid-year excludes quarter-ends already in the past', () => {
    const res = computeFrequencyAmounts(1000, 6, 'quarterly') // start Jul (index 6) -> Mar(2), Jun(5) already passed
    expect(res.map((r) => r.monthIndex)).toEqual([8, 11])
  })

  it('semiannual — only Jun and Dec, filtered to the start onward', () => {
    const res = computeFrequencyAmounts(1000, 0, 'semiannual')
    expect(res.map((r) => r.monthIndex)).toEqual([5, 11])
  })

  it('semiannual starting after June only yields December', () => {
    const res = computeFrequencyAmounts(1000, 7, 'semiannual')
    expect(res.map((r) => r.monthIndex)).toEqual([11])
  })

  it('bimonthly — every other absolute month (Feb/Apr/Jun/Aug/Oct/Dec)', () => {
    const res = computeFrequencyAmounts(1000, 0, 'bimonthly')
    expect(res.map((r) => r.monthIndex)).toEqual([1, 3, 5, 7, 9, 11])
  })

  it('applies the % adjustment before rounding', () => {
    const res = computeFrequencyAmounts(1000, 0, 'once', 10, 0)
    expect(res).toEqual([{ monthIndex: 0, value: 1100 }])
  })

  it('applies rounding after the % adjustment', () => {
    const res = computeFrequencyAmounts(1234, 0, 'once', 0, 100)
    expect(res).toEqual([{ monthIndex: 0, value: 1200 }])
  })

  it('returns an empty array for a non-finite base amount', () => {
    expect(computeFrequencyAmounts(NaN, 0, 'monthly')).toEqual([])
  })
})

describe('applyFrequencyCopy', () => {
  it('quarterly leaves the non-target months untouched', () => {
    const months = Array(12).fill('')
    months[0] = '1000'
    const next = applyFrequencyCopy(months, 0, 'quarterly')
    expect(next[0]).toBe('1000') // source month is index 0, not a quarterly target itself — untouched
    expect(next[2]).toBe('1000')
    expect(next[5]).toBe('1000')
    expect(next[8]).toBe('1000')
    expect(next[11]).toBe('1000')
    expect(next[1]).toBe('') // skipped month stays blank
    expect(next[3]).toBe('')
  })

  it('is a no-op when the source cell is empty/non-numeric', () => {
    const months = Array(12).fill('')
    const next = applyFrequencyCopy(months, 3, 'monthly')
    expect(next).toEqual(months)
  })

  it('does not mutate the original array', () => {
    const months = Array(12).fill('')
    months[0] = '1000'
    const copy = [...months]
    applyFrequencyCopy(months, 0, 'monthly')
    expect(months).toEqual(copy)
  })
})

describe('sumRowMonths / sumColumnAcrossRows', () => {
  const rows: GridRow[] = [
    { key: 'a', category_name: 'Sales', category_type: 'revenue', account: '', months: ['100', '', '200', ...Array(9).fill('')] },
    { key: 'b', category_name: 'Rent', category_type: 'expense', account: '', months: ['50', '50', '', ...Array(9).fill('')] },
  ]

  it('sums a single row across all 12 months, treating blanks as 0', () => {
    expect(sumRowMonths(rows[0])).toBe(300)
    expect(sumRowMonths(rows[1])).toBe(100)
  })

  it('sums one month column across all rows', () => {
    expect(sumColumnAcrossRows(rows, 0)).toBe(150) // 100 + 50
    expect(sumColumnAcrossRows(rows, 1)).toBe(50)  // 0 + 50
    expect(sumColumnAcrossRows(rows, 2)).toBe(200) // 200 + 0
  })
})

describe('computeSubtotals', () => {
  function mkAccount(id: string, account_type: Account['account_type']): Account {
    return {
      id, code: id, name: id, account_type,
      parent: null, description: '', is_active: true,
      is_system: false, balance: '0',
    }
  }

  const cogsAccount = mkAccount('acc-cogs', 'cogs')
  const expenseAccount = mkAccount('acc-exp', 'expense')
  const accounts: Account[] = [cogsAccount, expenseAccount]

  it('splits revenue, cogs-linked expense, and plain expense into the right buckets', () => {
    const rows: GridRow[] = [
      { key: 'sales', category_name: 'Sales', category_type: 'revenue', account: '', months: ['1000', ...Array(11).fill('')] },
      { key: 'cogs', category_name: 'Cost of Goods', category_type: 'expense', account: 'acc-cogs', months: ['300', ...Array(11).fill('')] },
      { key: 'rent', category_name: 'Rent', category_type: 'expense', account: 'acc-exp', months: ['100', ...Array(11).fill('')] },
      { key: 'misc', category_name: 'Misc (no account)', category_type: 'expense', account: '', months: ['50', ...Array(11).fill('')] },
    ]
    const res = computeSubtotals(rows, accounts)
    expect(res.totalSales[0]).toBe(1000)
    expect(res.costOfSales[0]).toBe(300)
    expect(res.grossProfit[0]).toBe(700) // 1000 - 300
    expect(res.totalExpenses[0]).toBe(150) // rent (100) + misc-no-account (50), NOT cogs
    expect(res.netProfit[0]).toBe(550) // 700 - 150
  })

  it('an expense row with no linked account is never classified as cost of sales', () => {
    const rows: GridRow[] = [
      { key: 'misc', category_name: 'Misc', category_type: 'expense', account: '', months: ['999', ...Array(11).fill('')] },
    ]
    const res = computeSubtotals(rows, accounts)
    expect(res.costOfSales[0]).toBe(0)
    expect(res.totalExpenses[0]).toBe(999)
  })

  it('returns all-zero arrays for an empty row set', () => {
    const res = computeSubtotals([], accounts)
    expect(res.totalSales).toEqual(Array(12).fill(0))
    expect(res.netProfit).toEqual(Array(12).fill(0))
  })
})
