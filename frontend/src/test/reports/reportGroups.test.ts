import { describe, it, expect } from 'vitest'
import { REPORT_GROUPS, REPORT_KEY_ALIASES, groupOfReport, placedReportKeys, visibleGroups, QUICK_LINKS, type Need } from '@/lib/reportGroups'
import type { CatalogEntry } from '@/lib/reportCategories'

// The 33 reports the catalog lists in backend/apps/reports/registry.py (keys and labels must not change).
const REGISTRY: [string, string][] = [
  ['profit-loss', 'Profit & Loss'], ['cash-flow', 'Cash Flow Report'], ['balance-sheet', 'Balance Sheet'],
  ['trial-balance', 'Trial Balance'], ['vat-return', 'Net Tax Report (VAT worksheet)'], ['tax-summary', 'Tax Summary Report'],
  ['financial-report-pack', 'Financial Report Pack'], ['changes-in-equity', 'Statement of Changes in Equity'],
  ['notes', 'Notes to the Financial Statements'], ['account-list', 'Account List'], ['cash-register', 'Cash Register Report'],
  ['pay-bills', 'Pay Bills Report'], ['deposits', 'Deposit Report'], ['gl-detail', 'Transaction Report (GL Detail)'],
  ['payments', 'Payments'], ['journal-register', 'Journal Register'], ['sales-by-customer', 'Sales By Customer'],
  ['customers-report', 'Customers Report'], ['customer-receipts', 'Customer Receipts'], ['purchases-report', 'Purchases Report'],
  ['purchase-returns', 'Purchase Return'], ['product-purchases', 'Product Purchases Report'], ['suppliers-report', 'Suppliers Report'],
  ['stock-report', 'Stock Report'], ['stock-valuation', 'Stock Valuation Report'], ['asset-register', 'Asset Register'],
  ['assets-by-category', 'Asset By Category'], ['assets-by-location', 'Asset By Location'],
  ['depreciation-report', 'Depreciation Report'], ['depreciation-method', 'Depreciation Method Report'],
  ['employee-list', 'Employee List'], ['payroll-report', 'Payroll Report'], ['attendance-summary', 'Attendance Summary'],
]
const catalogOf = (keys: string[]): CatalogEntry[] =>
  keys.map((k) => ({ key: k, label: REGISTRY.find((r) => r[0] === k)?.[1] ?? k, category: 'x', description: '', needs_period: true }))
const ALL = catalogOf(REGISTRY.map((r) => r[0]))
const everything = () => true
const nothing = () => false
const only = (...needs: Need[]) => (n: Need) => needs.includes(n)

describe('Reports home grouping', () => {
  it('keeps the old gl-tax-summary key working as tax-summary', () => {
    expect(REPORT_KEY_ALIASES['gl-tax-summary']).toBe('tax-summary')
  })

  it('has the eight business questions in the approved order', () => {
    expect(REPORT_GROUPS.map((g) => g.name)).toEqual([
      'How am I doing?', 'Who owes me?', 'What do I owe?', 'Where is my cash?', 'What is in stock?',
      'What do I owe the tax office?', 'People and payroll', 'The books',
    ])
  })

  it('places all 33 registry reports exactly once (nothing is lost, nothing is doubled)', () => {
    const placed = placedReportKeys()
    expect(REGISTRY).toHaveLength(33)
    expect([...placed].sort()).toEqual(REGISTRY.map((r) => r[0]).sort())
    expect(new Set(placed).size).toBe(placed.length)
  })

  it('every report is reachable from the owner home', () => {
    const vis = visibleGroups(ALL, everything)
    const reachable = new Set(vis.flatMap((g) => g.entries.flatMap((e) => [e.main, ...e.also])).flatMap((t) => (t.key ? [t.key] : [])))
    expect(reachable.size).toBe(33)
    expect(vis.some((g) => g.group.id === 'other')).toBe(false)
  })

  it('every old shortcut destination is still offered to the owner', () => {
    const to = new Set(visibleGroups(ALL, everything).flatMap((g) => g.entries.flatMap((e) => [e.main, ...e.also])).map((t) => t.to))
    for (const url of [
      '/reports?tab=pnl', '/reports/balance-sheet', '/reports/stock', '/reports/sales-by-customer',
      '/reports/sales-by-product', '/owner-analytics',
    ]) expect(to.has(url), url).toBe(true)
    expect(QUICK_LINKS.map((q) => q.to)).toEqual([
      '/reports', '/reports/balance-sheet', '/reports/stock', '/reports/sales-by-customer', '/reports/sales-by-product',
    ])
  })

  it('a member with no ticks and an empty report list sees nothing (no broken tile)', () => {
    expect(visibleGroups([], nothing)).toEqual([])
  })

  it('a Reports-only member sees only what the server lists, and no screen that needs another tick', () => {
    const vis = visibleGroups(catalogOf(['sales-by-customer', 'cash-flow']), only('reports'))
    const ids = vis.map((g) => g.group.id)
    expect(ids).toContain('how')
    expect(ids).toContain('cash')
    expect(ids).not.toContain('books')
    expect(ids).not.toContain('people')
    expect(ids).not.toContain('tax')
    const how = vis.find((g) => g.group.id === 'how')!
    const labels = how.entries.map((e) => e.entry.label)
    expect(labels).toContain('Sales by Customer')
    expect(labels).not.toContain('Profit & Loss')
    expect(labels).not.toContain('Owner view')
    for (const g of vis) for (const e of g.entries) expect(e.main).toBeTruthy()
  })

  it('an Accounting member gets the books group and Profit & Loss', () => {
    const vis = visibleGroups(catalogOf(['balance-sheet', 'trial-balance', 'profit-loss']), only('reports', 'accounting', 'profitLoss'))
    const books = vis.find((g) => g.group.id === 'books')!
    expect(books.entries.map((e) => e.entry.id)).toEqual(expect.arrayContaining(['balance-sheet', 'trial-balance', 'general-ledger']))
    const bs = books.entries.find((e) => e.entry.id === 'balance-sheet')!
    expect(bs.main.to).toBe('/reports/balance-sheet')
    expect(bs.also.map((t) => t.key)).toEqual(['balance-sheet'])
    expect(vis.find((g) => g.group.id === 'how')!.entries.map((e) => e.entry.id)).toContain('profit-loss')
  })

  it('falls back to the table report when the charts screen is not allowed', () => {
    const vis = visibleGroups(catalogOf(['profit-loss']), nothing)
    const pl = vis.find((g) => g.group.id === 'how')!.entries.find((e) => e.entry.id === 'profit-loss')!
    expect(pl.main.to).toBe('/reports/all?report=profit-loss')
    expect(pl.also).toHaveLength(0)
  })

  it('a report the backend adds later shows under Other reports instead of vanishing', () => {
    const vis = visibleGroups([...ALL, ...catalogOf(['brand-new-report'])], everything)
    const other = vis.find((g) => g.group.id === 'other')!
    expect(other.entries.map((e) => e.entry.id)).toEqual(['brand-new-report'])
  })

  it('finds the group a report belongs to (for the breadcrumb)', () => {
    expect(groupOfReport('trial-balance')?.id).toBe('books')
    expect(groupOfReport('payroll-report')?.id).toBe('people')
    expect(groupOfReport('nope')).toBeNull()
  })

  it('Notes is marked as a template until it has real content', () => {
    const notes = REPORT_GROUPS.flatMap((g) => g.entries).find((e) => e.id === 'notes')!
    expect(notes.badge).toBe('Template')
  })
})
