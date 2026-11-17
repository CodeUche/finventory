/**
 * Checks that a statement answer really has the parts the statement pop-up reads.
 * When the request fails, or the app is offline with nothing saved, the answer can be
 * an empty placeholder (for example { results: [] }); reading summary.opening_balance
 * on that used to blank the whole app. These checks let the pop-up show a plain
 * message with a Retry button instead.
 */
function isObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

export function isSupplierStatement(v: unknown): boolean {
  return isObject(v) && isObject(v.summary) && Array.isArray(v.bills) && Array.isArray(v.payments)
}

export function isCustomerStatement(v: unknown): boolean {
  return isObject(v) && isObject(v.summary) && Array.isArray(v.invoices) && Array.isArray(v.payments)
}
