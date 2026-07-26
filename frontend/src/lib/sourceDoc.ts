// Maps a journal entry's source_type to a human label and (where possible) an
// in-app route, so a ledger line can drill back to the document that created it.

export function sourceDocLabel(sourceType: string): string {
  const map: Record<string, string> = {
    sale: 'Invoice',
    invoice_void: 'Invoice (voided)',
    bill: 'Bill',
    expense: 'Expense',
    payroll: 'Payroll run',
    purchase_return: 'Purchase return',
    opening_balance: 'Opening balance',
    year_end_close: 'Year-end close',
    reversal: 'Reversal',
    credit_payment: 'Customer receipt',
    bill_payment: 'Supplier payment',
    '': 'Manual journal',
  }
  return map[sourceType] ?? sourceType
}

/**
 * Best-effort in-app route for a source document. Returns null when the source has
 * no dedicated page (e.g. opening balances, year-end close, manual journals) — the
 * caller then falls back to opening the journal entry itself.
 */
export function sourceDocRoute(sourceType: string): string | null {
  const map: Record<string, string> = {
    sale: '/sales',
    invoice_void: '/sales',
    bill: '/bills',
    expense: '/expenses',
    payroll: '/payroll/runs',
    purchase_return: '/purchases',
    credit_payment: '/credits',
  }
  return map[sourceType] ?? null
}
