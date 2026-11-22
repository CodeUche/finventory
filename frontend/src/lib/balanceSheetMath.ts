/**
 * Balance Sheet figures worked out on exact decimal units (lib/money.ts), never on floats.
 * Adding balances such as 0.1 + 0.2 in floating point gives 0.30000000000000004; here every
 * amount is a whole number of 1/10,000ths until the final division for a ratio.
 */
import { fromUnits, sumUnits, toUnits } from '@/lib/money'

export interface BSLine { code: string; balance: string | number }

const ZERO = BigInt(0)
const ONE_CENT = BigInt(100) // 0.01 in 1/10,000ths

const s = (v: unknown): string => String(v ?? 0)

/** Exact sum of the balances of the accounts whose numeric code is in [from, to]. */
export function sumCodeRange(accounts: BSLine[], from: number, to: number): bigint {
  return sumUnits(accounts.filter(a => { const c = parseInt(a.code, 10); return c >= from && c <= to }).map(a => s(a.balance)))
}

/** Exact total of a list of balances, as a decimal string ("1234.5000"). */
export function exactTotal(balances: Array<string | number>): string {
  return fromUnits(sumUnits(balances.map(s)))
}

/** Plain number for charts and display only, from exact units. */
export const unitsToNumber = (u: bigint): number => Number(fromUnits(u))

export function balanceSheetFigures(input: {
  assets: BSLine[]; liabilities: BSLine[]
  total_assets?: string | number; total_liabilities?: string | number; total_equity?: string | number
  unreconciled_amount?: string | number; ledger_out_of_balance?: boolean
}) {
  const totalAssets = toUnits(s(input.total_assets))
  const totalLiab = toUnits(s(input.total_liabilities))
  const totalEquity = toUnits(s(input.total_equity))
  const abs = (u: bigint) => (u < ZERO ? -u : u)

  const currentAssets = sumCodeRange(input.assets, 1000, 1499)
  const fixedAssets = sumCodeRange(input.assets, 1500, 1599)
  const otherAssets = sumCodeRange(input.assets, 1600, 1999)
  const currentLiab = sumCodeRange(input.liabilities, 2000, 2499)

  const ratio = (a: bigint, b: bigint): number | null => (b > ZERO ? Number(a) / Number(b) : null)

  return {
    totalAssets: unitsToNumber(totalAssets),
    totalLiab: unitsToNumber(totalLiab),
    totalEquity: unitsToNumber(totalEquity),
    totalLiabEquity: unitsToNumber(totalLiab + totalEquity),
    unreconciledAmount: unitsToNumber(abs(toUnits(s(input.unreconciled_amount)))),
    isBalanced: input.ledger_out_of_balance !== true && abs(totalAssets - (totalLiab + totalEquity)) < ONE_CENT,
    assetDonut: [
      { name: 'Current Assets', value: unitsToNumber(abs(currentAssets)) },
      { name: 'Fixed Assets', value: unitsToNumber(abs(fixedAssets)) },
      { name: 'Other Assets', value: unitsToNumber(abs(otherAssets)) },
    ].filter(d => d.value > 0),
    structureDonut: [
      { name: 'Liabilities', value: unitsToNumber(abs(totalLiab)) },
      { name: 'Equity', value: unitsToNumber(abs(totalEquity)) },
    ].filter(d => d.value > 0),
    workingCapital: unitsToNumber(currentAssets - currentLiab),
    currentRatio: ratio(currentAssets, currentLiab),
    debtEquityRatio: ratio(totalLiab, totalEquity),
  }
}
