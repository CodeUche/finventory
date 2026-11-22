import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { asList } from '@/lib/asList'
import { isSupplierStatement, isCustomerStatement } from '@/lib/statementShape'
import { resolveAccountGroup } from '@/lib/coaGroup'
import { glHealthNote } from '@/lib/glHealthMessage'
import RouteErrorBoundary from '@/components/RouteErrorBoundary'
import type { AccountTaxonomyGroup } from '@/types'

describe('asList', () => {
  it('keeps a bare list, unwraps a paged answer, and never throws on anything else', () => {
    expect(asList<number>([1, 2])).toEqual([1, 2])
    expect(asList<number>({ results: [3] })).toEqual([3])
    // the offline placeholder with nothing saved
    expect(asList<number>({ results: [] })).toEqual([])
    expect(asList<number>(null)).toEqual([])
    expect(asList<number>(undefined)).toEqual([])
    expect(asList<number>('x')).toEqual([])
    expect(asList<number>({ summary: {} })).toEqual([])
    // the spread that used to throw "not iterable"
    expect(() => [...asList<number>({ results: [] })]).not.toThrow()
  })
})

describe('statement shape guards', () => {
  it('rejects the offline placeholder and accepts a real statement', () => {
    expect(isSupplierStatement({ results: [] })).toBe(false)
    expect(isSupplierStatement(null)).toBe(false)
    expect(isSupplierStatement({ summary: {}, bills: [], payments: [] })).toBe(true)
    expect(isCustomerStatement({ results: [] })).toBe(false)
    expect(isCustomerStatement({ summary: {}, invoices: [], payments: [] })).toBe(true)
    expect(isCustomerStatement({ summary: {}, invoices: [] })).toBe(false)
  })
})

describe('resolveAccountGroup', () => {
  const tax: AccountTaxonomyGroup[] = [
    { group: 'Cash', statement: 'bs', base_account_type: 'asset', sub_types: [{ id: 's1', name: 'Bank', base_account_type: 'asset' }] },
    { group: 'Receivables', statement: 'bs', base_account_type: 'asset', sub_types: [{ id: 's2', name: 'Trade', base_account_type: 'asset' }] },
    { group: 'Sales', statement: 'pl', base_account_type: 'revenue', sub_types: [] },
  ]
  it('uses the saved group, then the sub type, then a unique base type', () => {
    expect(resolveAccountGroup(tax, { account_group: 'Cash', account_type: 'asset' })).toBe('Cash')
    expect(resolveAccountGroup(tax, { account_group: '', sub_type: 's2', account_type: 'asset' })).toBe('Receivables')
    expect(resolveAccountGroup(tax, { account_group: null, account_type: 'revenue' })).toBe('Sales')
    // two asset groups and nothing else to go on: do not guess
    expect(resolveAccountGroup(tax, { account_group: '', account_type: 'asset' })).toBe('')
  })
})

describe('glHealthNote', () => {
  const ok = { posted: 10, failed: 0, not_configured: 0, pending: 0 }
  it('says all posted only when nothing is pending, failed or out of balance', () => {
    expect(glHealthNote(ok, { is_balanced: true, all_reconciled: true }).tone).toBe('good')
    expect(glHealthNote({ ...ok, pending: 5 }).tone).toBe('warn')
    expect(glHealthNote({ ...ok, pending: 5 }).title).toMatch(/5 entries are still waiting/)
    expect(glHealthNote(ok, { is_balanced: true, all_reconciled: false }).tone).toBe('bad')
    expect(glHealthNote({ ...ok, failed: 1 }).tone).toBe('bad')
  })
})

function Boom(): never { throw new Error('kaboom') }

describe('RouteErrorBoundary', () => {
  it('shows the themed card with both actions instead of a blank screen', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<MemoryRouter><RouteErrorBoundary><Boom /></RouteErrorBoundary></MemoryRouter>)
    expect(screen.getByText('Something went wrong')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Go to dashboard' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    spy.mockRestore()
  })
})
