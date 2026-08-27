import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Module-level active currency — set once on app load from org settings
let _activeCurrency = 'NGN'
export function setActiveCurrency(c: string) { _activeCurrency = c }
export function getActiveCurrency() { return _activeCurrency }

// Intl's 'en' locale lacks narrow-symbol data for several currencies (NGN
// notably renders as the literal code "NGN" instead of "₦") — hardcode the
// symbols we actually need and only fall back to Intl for anything else.
const CURRENCY_SYMBOLS: Record<string, string> = {
  NGN: '₦', USD: '$', GBP: '£', EUR: '€', GHS: '₵', KES: 'KSh', ZAR: 'R', XOF: 'CFA',
}

// Single source of truth for "which currencies can an org pick" — used by
// both the TopBar quick-switch pill and Settings > Profile > Currency. Two
// independently maintained lists previously existed here and drifted apart;
// don't reintroduce a second one.
export const SUPPORTED_CURRENCIES = [
  'NGN', 'USD', 'EUR', 'GBP', 'GHS', 'KES', 'ZAR', 'XOF', 'XAF',
  'EGP', 'MAD', 'TZS', 'UGX', 'RWF', 'ZMW', 'BWP',
]

/** Extract just the currency symbol (e.g. '₦', '$', '£') for the active or given currency. */
export function getCurrencySymbol(currency?: string): string {
  const cur = currency ?? _activeCurrency
  if (CURRENCY_SYMBOLS[cur]) return CURRENCY_SYMBOLS[cur]
  try {
    // Format 0, then strip digits, commas, spaces, dots — what's left is the symbol
    const formatted = new Intl.NumberFormat('en', {
      style: 'currency', currency: cur, minimumFractionDigits: 0, maximumFractionDigits: 0,
    }).format(0)
    return formatted.replace(/[\d,.\s]/g, '').trim() || cur
  } catch {
    return cur
  }
}

export function formatCurrency(value: string | number, currency?: string): string {
  const cur = currency ?? _activeCurrency
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return `${getCurrencySymbol(cur)}0.00`
  const symbol = getCurrencySymbol(cur)
  const sign = num < 0 ? '-' : ''
  const formattedNum = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(num))
  return `${sign}${symbol}${formattedNum}`
}

export function formatNumber(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  return new Intl.NumberFormat('en-NG').format(num)
}

export function formatDate(dateStr: string): string {
  if (!dateStr) return ''
  // Parse safely — handles both "2025-12-31" and "2025-12-31T..." ISO strings
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  // Use UTC parts to avoid timezone-offset shifting the date by a day
  const day = String(d.getUTCDate()).padStart(2, '0')
  const month = String(d.getUTCMonth() + 1).padStart(2, '0')
  const year = d.getUTCFullYear()
  return `${day}/${month}/${year}`
}

/** Strip commas before sending a formatted amount to the API */
export function stripCommas(v: string): string {
  return v.replace(/,/g, '')
}

/** Format a raw string as a comma-separated number while the user types */
export function formatAmountInput(raw: string): string {
  const cleaned = raw.replace(/[^0-9.]/g, '').replace(/^(\d*\.?\d*).*$/, '$1')
  const [intPart, decPart] = cleaned.split('.')
  const formatted = intPart ? Number(intPart).toLocaleString('en') : ''
  return decPart !== undefined ? `${formatted}.${decPart}` : formatted
}

/** Normalize an API-sourced decimal string for display in an amount input — strips trailing zeros */
export function normalizeAmountStr(v: string | null | undefined): string {
  const num = parseFloat(v ?? '0')
  if (isNaN(num)) return ''
  const normalized = num % 1 === 0 ? String(Math.round(num)) : String(num)
  return formatAmountInput(normalized)
}

export function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    paid: 'badge-green',
    confirmed: 'badge-blue',
    partially_paid: 'badge-yellow',
    credit: 'badge-orange',
    overdue: 'badge-red',
    voided: 'badge-slate',
    draft: 'badge-slate',
    returned: 'badge-purple',
    active: 'badge-green',
    trialing: 'badge-blue',
    canceled: 'badge-red',
  }
  return map[status] ?? 'badge-slate'
}
