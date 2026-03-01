import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Module-level active currency — set once on app load from org settings
let _activeCurrency = 'NGN'
export function setActiveCurrency(c: string) { _activeCurrency = c }
export function getActiveCurrency() { return _activeCurrency }

export function formatCurrency(value: string | number, currency?: string): string {
  const cur = currency ?? _activeCurrency
  const num = typeof value === 'string' ? parseFloat(value) : value
  try {
    return new Intl.NumberFormat('en', {
      style: 'currency',
      currency: cur,
      minimumFractionDigits: 2,
    }).format(num)
  } catch {
    // Fallback if currency code is invalid
    return `${cur} ${num.toFixed(2)}`
  }
}

export function formatNumber(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  return new Intl.NumberFormat('en-NG').format(num)
}

export function formatDate(dateStr: string): string {
  return new Intl.DateTimeFormat('en-NG', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(dateStr))
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
    active: 'badge-green',
    trialing: 'badge-blue',
    canceled: 'badge-red',
  }
  return map[status] ?? 'badge-slate'
}
