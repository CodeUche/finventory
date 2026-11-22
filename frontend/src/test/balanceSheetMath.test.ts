import { describe, expect, it } from 'vitest'
import { balanceSheetFigures, exactTotal } from '@/lib/balanceSheetMath'

describe('balance sheet money maths is exact', () => {
  it('adds 0.1 + 0.2 to exactly 0.3 (floating point gives 0.30000000000000004)', () => {
    expect(0.1 + 0.2).not.toBe(0.3)
    expect(Number(exactTotal(['0.1', '0.2']))).toBe(0.3)
  })

  it('sums many awkward balances without drift', () => {
    const ten = Array.from({ length: 10 }, () => '0.1')
    expect(exactTotal(ten)).toBe('1.0000')
    expect(exactTotal(['1234567.89', '-0.89', '0.01'])).toBe('1234567.0100')
  })

  it('works out the donut, ratios and balanced flag from exact units', () => {
    const f = balanceSheetFigures({
      assets: [
        { code: '1001', balance: '0.1' }, { code: '1100', balance: '0.2' },
        { code: '1510', balance: '50.5' }, { code: '1700', balance: '9.25' },
      ],
      liabilities: [{ code: '2001', balance: '0.15' }],
      total_assets: '60.05', total_liabilities: '0.15', total_equity: '59.90',
    })
    expect(f.assetDonut).toEqual([
      { name: 'Current Assets', value: 0.3 }, // exactly 0.3, not 0.30000000000000004
      { name: 'Fixed Assets', value: 50.5 },
      { name: 'Other Assets', value: 9.25 },
    ])
    expect(f.currentRatio).toBe(2) // 0.3 / 0.15
    expect(f.workingCapital).toBe(0.15)
    expect(f.debtEquityRatio).toBeCloseTo(0.15 / 59.9, 10)
    expect(f.isBalanced).toBe(true) // 60.05 = 0.15 + 59.90
  })

  it('is not balanced when the ledger is out of balance, and has no current ratio without a current liability', () => {
    const f = balanceSheetFigures({
      assets: [], liabilities: [], total_assets: '10', total_liabilities: '0', total_equity: '10',
      ledger_out_of_balance: true,
    })
    expect(f.isBalanced).toBe(false)
    expect(f.currentRatio).toBeNull()
    expect(f.debtEquityRatio).toBe(0) // no liabilities over positive equity
  })
})
