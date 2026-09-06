/**
 * Pure logic for the Budget monthly grid editor (Phase 3). Kept dependency-
 * free and side-effect-free so it can be unit tested directly — the
 * component just calls these and formats the result for display.
 */

import type { Account } from '@/types'

/** One row of the monthly grid: a category/account combination with a
 * budgeted amount per calendar month (index 0 = Jan .. 11 = Dec). Empty
 * string means "no value entered for this month" — it is left out of the
 * bulk-upsert submission entirely, it is never sent as 0. */
export interface GridRow {
  key: string
  category_name: string
  category_type: 'expense' | 'revenue'
  account: string
  months: string[] // length 12, raw numeric strings (no commas) or ''
}

/**
 * "Copy forward" a filled cell's value across the remaining months of its
 * row, with an optional one-off flat % adjustment (not compounding month over
 * month — Sage 50's simpler mode, per spec). Returns only the values for the
 * months AFTER fromMonthIndex (i.e. length = 11 - fromMonthIndex); the
 * caller splices them into its own row state.
 *
 * @param baseAmount     the source cell's numeric value (already parsed)
 * @param fromMonthIndex 0-11, the month being copied FROM
 * @param percentAdjust  e.g. 10 for +10%, -5 for -5%; 0/undefined = no change
 */
export function computeCopyForwardAmounts(
  baseAmount: number,
  fromMonthIndex: number,
  percentAdjust = 0,
): number[] {
  if (!Number.isFinite(baseAmount) || fromMonthIndex < 0 || fromMonthIndex > 11) return []
  const remaining = 11 - fromMonthIndex
  if (remaining <= 0) return []
  const factor = 1 + (Number.isFinite(percentAdjust) ? percentAdjust : 0) / 100
  const adjusted = Math.round(baseAmount * factor * 100) / 100
  return Array.from({ length: remaining }, () => adjusted)
}

/** Applies computeCopyForwardAmounts to a row's months array, returning a
 * NEW months array (immutable — safe for React state updates) with months
 * after fromMonthIndex overwritten. */
export function applyCopyForward(months: string[], fromMonthIndex: number, percentAdjust = 0): string[] {
  const base = parseFloat(months[fromMonthIndex] || '')
  if (isNaN(base)) return months
  const values = computeCopyForwardAmounts(base, fromMonthIndex, percentAdjust)
  const next = [...months]
  values.forEach((v, i) => { next[fromMonthIndex + 1 + i] = String(v) })
  return next
}

// ── Phase 6 (B3/B3b): "Copy Budget Values" with a frequency + rounding ──────
// A SEPARATE, additive feature from the copy-forward pair above (which stays
// exactly as-is — same behavior, same tests). This one fills a row's months
// from a chosen starting month using a fixed calendar-frequency pattern
// (e.g. quarterly always means Mar/Jun/Sep/Dec, not "every 3rd month from
// wherever you started"), optionally rounding the result to the nearest N.

export type CopyFrequency = 'once' | 'monthly' | 'bimonthly' | 'quarterly' | 'semiannual'

/** Absolute calendar-month indices (0=Jan..11=Dec) that receive a value for
 * a given frequency, BEFORE filtering to >= fromMonthIndex. */
function frequencyTargetMonths(frequency: CopyFrequency): number[] {
  switch (frequency) {
    case 'once': return [] // handled specially — see computeFrequencyAmounts
    case 'monthly': return Array.from({ length: 12 }, (_, i) => i)
    case 'bimonthly': return [1, 3, 5, 7, 9, 11]
    case 'quarterly': return [2, 5, 8, 11]
    case 'semiannual': return [5, 11]
  }
}

/** Rounds a value to the nearest multiple of `nearest` (e.g. nearest=100
 * rounds 1,234 to 1,200). nearest<=0 or a non-finite value is a no-op. */
export function roundToNearest(value: number, nearest: number): number {
  if (!Number.isFinite(value) || !nearest || nearest <= 0) return value
  return Math.round(value / nearest) * nearest
}

/**
 * Computes which months (by absolute index) get a value and what that value
 * is, for the new frequency-based "Copy Budget Values" feature. Unlike
 * computeCopyForwardAmounts (which only ever fills every remaining month
 * with one flat value, starting AFTER the source cell), this:
 *   - can leave gaps (quarterly/semiannual/bimonthly skip months)
 *   - for 'monthly', DOES include fromMonthIndex itself (a "fill from here
 *     to year-end" operation on a freshly-typed base amount, not a "copy an
 *     existing value forward" operation)
 *   - for 'once', only ever touches fromMonthIndex itself
 *   - optionally rounds the result to the nearest N after the % adjustment
 */
export function computeFrequencyAmounts(
  baseAmount: number,
  fromMonthIndex: number,
  frequency: CopyFrequency,
  percentAdjust = 0,
  roundTo = 0,
): Array<{ monthIndex: number; value: number }> {
  if (!Number.isFinite(baseAmount) || fromMonthIndex < 0 || fromMonthIndex > 11) return []

  const factor = 1 + (Number.isFinite(percentAdjust) ? percentAdjust : 0) / 100
  let adjusted = Math.round(baseAmount * factor * 100) / 100
  if (roundTo > 0) adjusted = roundToNearest(adjusted, roundTo)

  const targets = frequency === 'once'
    ? [fromMonthIndex]
    : frequencyTargetMonths(frequency).filter((m) => m >= fromMonthIndex)

  return targets.map((monthIndex) => ({ monthIndex, value: adjusted }))
}

/** Applies computeFrequencyAmounts to a row's months array, returning a NEW
 * array (immutable) with only the target month indices overwritten — every
 * other month (including any before fromMonthIndex, and any skipped by the
 * chosen frequency) is left exactly as it was. */
export function applyFrequencyCopy(
  months: string[],
  fromMonthIndex: number,
  frequency: CopyFrequency,
  percentAdjust = 0,
  roundTo = 0,
): string[] {
  const base = parseFloat(months[fromMonthIndex] || '')
  if (isNaN(base)) return months
  const results = computeFrequencyAmounts(base, fromMonthIndex, frequency, percentAdjust, roundTo)
  const next = [...months]
  results.forEach(({ monthIndex, value }) => { next[monthIndex] = String(value) })
  return next
}

// ── Phase 6 (B4c): row/column totals ────────────────────────────────────────

/** Sum of a single row's 12 month cells (blank/non-numeric cells count as 0). */
export function sumRowMonths(row: GridRow): number {
  return row.months.reduce((sum, m) => sum + (parseFloat(m) || 0), 0)
}

/** Sum of one month column across every row (blank/non-numeric cells count as 0). */
export function sumColumnAcrossRows(rows: GridRow[], monthIndex: number): number {
  return rows.reduce((sum, r) => sum + (parseFloat(r.months[monthIndex]) || 0), 0)
}

// ── Phase 6 (B4b): computed P&L subtotal rows ───────────────────────────────

export interface BudgetSubtotals {
  totalSales: number[]
  costOfSales: number[]
  grossProfit: number[]
  totalExpenses: number[]
  netProfit: number[]
}

/**
 * Per-month P&L subtotals derived purely from the grid's current rows.
 * BudgetLine/GridRow.category_type only distinguishes expense/revenue (no
 * separate "cogs" value) — Cost of Sales can only be identified via a row's
 * LINKED account having account_type === 'cogs'. A manually-typed expense
 * row with no account linked is always counted in totalExpenses, never
 * costOfSales — that's a deliberate limitation (COGS classification requires
 * a real Chart-of-Accounts link), not a bug.
 */
export function computeSubtotals(rows: GridRow[], accounts: Account[]): BudgetSubtotals {
  const accountById = new Map(accounts.map((a) => [a.id, a]))
  const totalSales = Array(12).fill(0)
  const costOfSales = Array(12).fill(0)
  const totalExpenses = Array(12).fill(0)

  for (const row of rows) {
    const acct = row.account ? accountById.get(row.account) : undefined
    for (let m = 0; m < 12; m++) {
      const val = parseFloat(row.months[m]) || 0
      if (val === 0) continue
      if (row.category_type === 'revenue') {
        totalSales[m] += val
      } else if (acct?.account_type === 'cogs') {
        costOfSales[m] += val
      } else {
        totalExpenses[m] += val
      }
    }
  }

  const grossProfit = totalSales.map((v, i) => v - costOfSales[i])
  const netProfit = grossProfit.map((v, i) => v - totalExpenses[i])

  return { totalSales, costOfSales, grossProfit, totalExpenses, netProfit }
}

/** Sums a list of budget lines' budgeted_amount for display purposes only
 * (e.g. the Budgets grid-view card total). Never used to build a value that
 * crosses back over the API boundary — that always stays server-computed
 * Decimal. */
export function sumBudgetedAmount(lines: { budgeted_amount: string | number }[]): number {
  return lines.reduce((sum, l) => {
    const n = typeof l.budgeted_amount === 'number' ? l.budgeted_amount : parseFloat(l.budgeted_amount)
    return sum + (Number.isFinite(n) ? n : 0)
  }, 0)
}

/** Builds the flat bulk_lines payload from the grid's row state — skips
 * rows with no category name and months with no value entered (so an empty
 * cell never becomes a submitted 0). */
export function buildBulkLinesPayload(rows: GridRow[]): Array<{
  category_name: string
  category_type: string
  account?: string
  period_month: number
  budgeted_amount: number
}> {
  const out: Array<{ category_name: string; category_type: string; account?: string; period_month: number; budgeted_amount: number }> = []
  for (const row of rows) {
    const name = row.category_name.trim()
    if (!name) continue
    row.months.forEach((raw, idx) => {
      const val = parseFloat(raw)
      if (raw === '' || raw === undefined || isNaN(val)) return
      out.push({
        category_name: name,
        category_type: row.category_type,
        ...(row.account ? { account: row.account } : {}),
        period_month: idx + 1,
        budgeted_amount: val,
      })
    })
  }
  return out
}
