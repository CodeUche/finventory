/**
 * Pure logic for the Budget monthly grid editor (Phase 3). Kept dependency-
 * free and side-effect-free so it can be unit tested directly — the
 * component just calls these and formats the result for display.
 */

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
