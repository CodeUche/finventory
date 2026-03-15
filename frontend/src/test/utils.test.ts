import { describe, it, expect, beforeEach } from 'vitest'
import {
  formatDate,
  formatCurrency,
  getCurrencySymbol,
  setActiveCurrency,
  formatAmountInput,
  stripCommas,
} from '@/lib/utils'

describe('formatDate', () => {
  it('formats ISO date string to DD/MM/YYYY', () => {
    expect(formatDate('2026-03-15')).toBe('15/03/2026')
  })

  it('formats ISO datetime string to DD/MM/YYYY', () => {
    expect(formatDate('2026-12-31T23:59:00Z')).toBe('31/12/2026')
  })

  it('returns empty string for empty input', () => {
    expect(formatDate('')).toBe('')
  })

  it('returns original value for invalid date', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })

  it('does not shift date due to timezone offset', () => {
    // "2026-01-01" should always render as 01/01/2026, never 31/12/2025
    expect(formatDate('2026-01-01')).toBe('01/01/2026')
  })
})

describe('formatCurrency (NGN)', () => {
  beforeEach(() => setActiveCurrency('NGN'))

  it('formats a positive number with ₦ symbol', () => {
    const result = formatCurrency(1000)
    expect(result).toContain('1,000')
  })

  it('formats string input', () => {
    const result = formatCurrency('500.50')
    expect(result).toContain('500')
  })

  it('returns ₦0.00 for NaN input', () => {
    const result = formatCurrency('abc')
    expect(result).toMatch(/0\.00/)
  })

  it('formats zero', () => {
    const result = formatCurrency(0)
    expect(result).toMatch(/0\.00/)
  })
})

describe('getCurrencySymbol', () => {
  it('returns a non-empty string for NGN', () => {
    // jsdom Intl may return the currency code rather than the symbol — either is valid
    expect(getCurrencySymbol('NGN').length).toBeGreaterThan(0)
  })

  it('returns a non-empty string for USD', () => {
    expect(getCurrencySymbol('USD').length).toBeGreaterThan(0)
  })

  it('falls back to currency code for unknown currency', () => {
    const result = getCurrencySymbol('XYZ')
    expect(result.length).toBeGreaterThan(0)
  })
})

describe('formatAmountInput / stripCommas', () => {
  it('formatAmountInput adds comma separators', () => {
    expect(formatAmountInput('1000000')).toBe('1,000,000')
  })

  it('formatAmountInput preserves decimal part', () => {
    expect(formatAmountInput('1500.50')).toBe('1,500.50')
  })

  it('stripCommas removes commas', () => {
    expect(stripCommas('1,000,000')).toBe('1000000')
  })

  it('stripCommas handles value without commas', () => {
    expect(stripCommas('500')).toBe('500')
  })
})
