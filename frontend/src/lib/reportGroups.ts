/**
 * The Reports home, grouped by business question (the approved "Option B" layout).
 *
 * Each group holds report ENTRIES. An entry is one thing a person wants to look at, and it can have
 * several TARGETS: the dedicated screen (charts, drill-down) and/or one or more reports from the
 * backend report registry (/reports/catalog/). The first target the person is allowed to open is
 * the main link; the others show as small "also" links, so nothing that used to be reachable is lost.
 *
 * Registry targets carry no permission rule of their own: the server only lists the reports a
 * person may run, so a registry target is shown only when it is in that list. Screen targets carry
 * a `need` list checked with the same hooks the screens already use.
 *
 * Every one of the 34 registry reports is placed here exactly once (a test checks it). A report the
 * backend adds later and that is not placed here is shown under "Other reports" so it is never hidden.
 */
import {
  BookOpen, Boxes, FileSpreadsheet, Landmark, Wallet, Receipt, ShoppingBag, TrendingUp, UsersRound,
} from 'lucide-react'
import type { CatalogEntry } from '@/lib/reportCategories'

/** What a screen target needs. Module names are the Team permission ticks. */
export type Need =
  | 'reports' | 'accounting' | 'inventory' | 'budget' | 'payroll' | 'tax' | 'sales' | 'customers' | 'suppliers'
  | 'owner'
  // Flags from useReportAccess (the figures a screen asks the server for).
  | 'profitLoss' | 'arAging' | 'apAging' | 'expenseBreakdown' | 'customerBalance' | 'inventoryValuation'

export interface ReportTarget {
  /** Where it opens. Registry targets open the General Reports viewer. */
  to: string
  /** Shown on the small "also" link when this is not the main target. */
  label: string
  /** Set for registry targets: the report key that must be in the catalog. */
  key?: string
  /** Set for screen targets: every need must pass. */
  need?: Need[]
}

export interface ReportEntry {
  id: string
  label: string
  /** One plain sentence under the name. */
  blurb: string
  targets: ReportTarget[]
  /** Small tag next to the name, e.g. "Template". */
  badge?: string
}

/** Which headline figure a group tile shows, if any. */
export type TileFigure = 'netProfit' | 'receivable' | 'payable' | 'cash' | 'vat'

export interface ReportGroup {
  id: string
  /** The business question. */
  name: string
  /** Plain description under the question. */
  blurb: string
  icon: React.ElementType
  figure?: TileFigure
  entries: ReportEntry[]
}

const rep = (key: string, label: string): ReportTarget => ({ to: `/reports/all?report=${key}`, label, key })
const screen = (to: string, label: string, need: Need[]): ReportTarget => ({ to, label, need })

export const REPORT_GROUPS: ReportGroup[] = [
  {
    id: 'how', name: 'How am I doing?', blurb: 'Profit, sales and spending', icon: TrendingUp, figure: 'netProfit',
    entries: [
      { id: 'profit-loss', label: 'Profit & Loss', blurb: 'What you earned, what it cost and what is left.',
        targets: [screen('/reports?tab=pnl', 'Charts view', ['reports', 'profitLoss']), rep('profit-loss', 'Table view')] },
      { id: 'sales-trend', label: 'Sales trend', blurb: 'How sales move over time.',
        targets: [screen('/reports?tab=sales_analytics', 'Sales analytics', ['reports'])] },
      { id: 'sales-by-customer', label: 'Sales by Customer', blurb: 'Who buys the most.',
        targets: [screen('/reports/sales-by-customer', 'Charts view', ['reports']), rep('sales-by-customer', 'Table view')] },
      { id: 'sales-by-product', label: 'Sales by Product', blurb: 'What sells best and what it earns.',
        targets: [screen('/reports/sales-by-product', 'Charts view', ['reports'])] },
      { id: 'sales-by-location', label: 'Sales by Location', blurb: 'Sales for each branch or shop.',
        targets: [screen('/locations', 'Locations', ['sales'])] },
      { id: 'expenses', label: 'Expenses', blurb: 'Where your money goes.',
        targets: [screen('/reports?tab=expenses', 'Expenses', ['reports', 'expenseBreakdown'])] },
      { id: 'budget', label: 'Budget vs actual', blurb: 'Spending against your budgets.',
        targets: [screen('/budgets/monitoring', 'Budget monitoring', ['budget'])] },
      { id: 'owner-view', label: 'Owner view', blurb: 'The owner-only overview. Owners and admins only.',
        targets: [screen('/owner-analytics', 'Owner Analytics', ['owner'])] },
    ],
  },
  {
    id: 'owe', name: 'Who owes me?', blurb: 'Customers who have not paid', icon: Receipt, figure: 'receivable',
    entries: [
      { id: 'aged-receivables', label: 'Aged Receivables', blurb: 'Unpaid customer invoices by how late they are.',
        targets: [screen('/reports?tab=aging', 'Aging', ['reports', 'arAging'])] },
      { id: 'customer-balances', label: 'Customer Balances', blurb: 'What each customer owes you now.',
        targets: [screen('/reports?tab=customer_gl', 'Customer balances', ['reports', 'customerBalance']), rep('customers-report', 'Table view')] },
      { id: 'customer-statements', label: 'Customer Statements', blurb: 'Open a customer to see their statement.',
        targets: [screen('/customers', 'Customers', ['customers'])] },
      { id: 'receipts', label: 'Receipts', blurb: 'Money received from customers.',
        targets: [rep('customer-receipts', 'Customer receipts'), rep('deposits', 'Deposit report')] },
    ],
  },
  {
    id: 'iowe', name: 'What do I owe?', blurb: 'Suppliers and bills to pay', icon: ShoppingBag, figure: 'payable',
    entries: [
      { id: 'aged-payables', label: 'Aged Payables', blurb: 'Unpaid supplier bills by how late they are.',
        targets: [screen('/reports?tab=aging', 'Aging', ['reports', 'apAging'])] },
      { id: 'supplier-balances', label: 'Supplier Balances and Statements', blurb: 'What you owe each supplier.',
        targets: [rep('suppliers-report', 'Suppliers report'), screen('/suppliers', 'Suppliers', ['suppliers'])] },
      { id: 'purchases', label: 'Purchases', blurb: 'What you bought, and what you sent back.',
        targets: [rep('purchases-report', 'Purchases report'), rep('purchase-returns', 'Purchase returns'), rep('product-purchases', 'By product')] },
      { id: 'payments-out', label: 'Payments out', blurb: 'Bills and other payments you made.',
        targets: [rep('pay-bills', 'Pay bills report'), rep('payments', 'Payments')] },
    ],
  },
  {
    id: 'cash', name: 'Where is my cash?', blurb: 'Money in, money out', icon: Wallet, figure: 'cash',
    entries: [
      { id: 'cash-movement', label: 'Cash movement', blurb: 'Cash that came in and went out.',
        targets: [screen('/reports?tab=cashflow', 'Charts view', ['reports']), rep('cash-flow', 'Table view')] },
      { id: 'cash-register', label: 'Cash Register', blurb: 'Every cash and bank movement with a running balance.',
        targets: [rep('cash-register', 'Cash register')] },
      { id: 'card-settlement', label: 'Card settlement', blurb: 'Card payments and when they reach your bank.',
        targets: [screen('/payments/settlement', 'Settlement', ['sales'])] },
    ],
  },
  {
    id: 'stock', name: 'What is in stock?', blurb: 'Quantities and value', icon: Boxes,
    entries: [
      { id: 'stock-levels', label: 'Stock Levels', blurb: 'How much of each item you hold.',
        targets: [screen('/reports/stock', 'Stock reports', ['inventory']), rep('stock-report', 'Table view')] },
      { id: 'inventory-value', label: 'Inventory Value', blurb: 'What your stock is worth. Owners and admins only.',
        targets: [screen('/reports/stock?tab=valuation', 'Stock reports', ['inventoryValuation']), rep('stock-valuation', 'Table view')] },
      { id: 'stock-card', label: 'Stock Card', blurb: 'The history of one item, in and out.',
        targets: [screen('/reports/stock?tab=stock_card', 'Stock card', ['inventory'])] },
      { id: 'usage-transfers', label: 'Usage and Transfers', blurb: 'What was used and what moved between places.',
        targets: [screen('/reports/stock?tab=usage', 'Usage', ['inventory']), screen('/reports/stock?tab=transfers', 'Transfers', ['inventory'])] },
    ],
  },
  {
    id: 'tax', name: 'What do I owe the tax office?', blurb: 'VAT, withholding tax, PAYE', icon: Landmark, figure: 'vat',
    entries: [
      { id: 'vat-return', label: 'VAT Return', blurb: 'VAT collected less VAT paid, for the period.',
        targets: [rep('vat-return', 'VAT worksheet'), screen('/tax', 'Tax page', ['tax'])] },
      { id: 'tax-summary', label: 'Tax Summary', blurb: 'VAT, withholding tax and PAYE in one view.',
        targets: [rep('tax-summary', 'Tax summary')] },
      { id: 'wht-more', label: 'WHT, Capital allowances, Deferred tax', blurb: 'These stay on the Tax page.',
        targets: [screen('/tax', 'Tax page', ['tax'])] },
      { id: 'paye-remittances', label: 'PAYE and Remittances', blurb: 'Payroll tax due and when to pay it.',
        targets: [screen('/hr/compliance', 'Compliance', ['payroll'])] },
    ],
  },
  {
    id: 'people', name: 'People and payroll', blurb: 'Payroll and staff reports', icon: UsersRound,
    entries: [
      { id: 'hr-analytics', label: 'HR Analytics', blurb: 'Headcount, pay cost and staff trends.',
        targets: [screen('/hr/analytics', 'HR Analytics', ['payroll'])] },
      { id: 'payroll-register', label: 'Payroll Register', blurb: 'Every pay run with its totals.',
        targets: [rep('payroll-report', 'Payroll report'), screen('/hr/runs', 'Pay runs', ['payroll'])] },
      { id: 'annual-paye', label: 'Annual PAYE Reconciliation', blurb: 'The year of PAYE, checked against what was paid.',
        targets: [screen('/hr/runs', 'Pay runs', ['payroll'])] },
      { id: 'attendance', label: 'Attendance Summary', blurb: 'Who was in, late or away.',
        targets: [rep('attendance-summary', 'Attendance summary')] },
      { id: 'employee-list', label: 'Employee List', blurb: 'Your staff with pay details. Needs the Payroll permission.',
        targets: [rep('employee-list', 'Employee list')] },
    ],
  },
  {
    id: 'books', name: 'The books', blurb: 'Statements and ledgers for the accountant', icon: BookOpen,
    entries: [
      { id: 'balance-sheet', label: 'Balance Sheet', blurb: 'What you own, what you owe and what is left.',
        targets: [screen('/reports/balance-sheet', 'Full view', ['accounting']), rep('balance-sheet', 'Table view')] },
      { id: 'trial-balance', label: 'Trial Balance', blurb: 'Every account with its balance.',
        targets: [rep('trial-balance', 'Trial balance'), screen('/accounting/coa', 'Chart of Accounts', ['accounting'])] },
      { id: 'general-ledger', label: 'General Ledger', blurb: 'Every posting, account by account.',
        targets: [screen('/accounting/general-ledger', 'Ledger', ['accounting']), rep('gl-detail', 'Transaction report'), rep('account-list', 'Account list')] },
      { id: 'journal-register', label: 'Journal Register', blurb: 'Every journal entry with its lines.',
        targets: [rep('journal-register', 'Journal register')] },
      { id: 'changes-in-equity', label: 'Statement of Changes in Equity', blurb: 'How the owners’ share moved in the period.',
        targets: [rep('changes-in-equity', 'Changes in equity')] },
      { id: 'report-pack', label: 'Financial Report Pack', blurb: 'Profit & Loss, Balance Sheet and Trial Balance together.',
        targets: [rep('financial-report-pack', 'Report pack')] },
      { id: 'fixed-assets', label: 'Fixed assets reports', blurb: 'Asset register, by category, by place, depreciation.',
        targets: [
          rep('asset-register', 'Asset register'), rep('assets-by-category', 'By category'), rep('assets-by-location', 'By location'),
          rep('depreciation-report', 'Depreciation'), rep('depreciation-method', 'By method'),
        ] },
      { id: 'notes', label: 'Notes to the Financial Statements', blurb: 'The notes that go with the statements.', badge: 'Template',
        targets: [rep('notes', 'Notes')] },
    ],
  },
]

/** The "Quick links" row on the Reports home: the shortcuts the old sub-menu offered. */
export interface QuickLink { label: string; to: string; need: Need[] }
export const QUICK_LINKS: QuickLink[] = [
  { label: 'Financial Statements (charts)', to: '/reports', need: ['reports'] },
  { label: 'Balance Sheet', to: '/reports/balance-sheet', need: ['accounting'] },
  { label: 'Stock Reports', to: '/reports/stock', need: ['inventory'] },
  { label: 'Sales by Customer', to: '/reports/sales-by-customer', need: ['reports'] },
  { label: 'Sales by Product', to: '/reports/sales-by-product', need: ['reports'] },
]

/** Old report keys that still work (saved links) and mean another report. Mirrors _ALIASES in backend/apps/reports/registry.py. */
export const REPORT_KEY_ALIASES: Record<string, string> = { 'gl-tax-summary': 'tax-summary' }

/** Group id the viewer opens a report under; `null` when the key is not placed in any group. */
export function groupOfReport(key: string): ReportGroup | null {
  return REPORT_GROUPS.find((g) => g.entries.some((e) => e.targets.some((t) => t.key === key))) ?? null
}

/** Every registry key placed in a group (for the "nothing is lost" check). */
export function placedReportKeys(): string[] {
  return REPORT_GROUPS.flatMap((g) => g.entries.flatMap((e) => e.targets.flatMap((t) => (t.key ? [t.key] : []))))
}

export interface VisibleEntry {
  entry: ReportEntry
  /** The main link. */
  main: ReportTarget
  /** The other allowed links. */
  also: ReportTarget[]
}
export interface VisibleGroup { group: ReportGroup; entries: VisibleEntry[] }

/**
 * What one person may see. A target shows when it is allowed; an entry shows when any target is;
 * a group shows when any entry does. Nothing is rendered that this person cannot open.
 * `catalog` is the list of reports the server says they may run. A report in it that no group
 * places (the backend added one) lands in "Other reports" so it is never hidden.
 */
export function visibleGroups(catalog: CatalogEntry[], can: (need: Need) => boolean): VisibleGroup[] {
  const catalogKeys = new Set(catalog.map((r) => r.key))
  const allowed = (t: ReportTarget) => (t.key ? catalogKeys.has(t.key) : (t.need ?? []).every(can))
  const out = REPORT_GROUPS
    .map((group) => ({
      group,
      entries: group.entries.flatMap((entry): VisibleEntry[] => {
        const ok = entry.targets.filter(allowed)
        return ok.length ? [{ entry, main: ok[0], also: ok.slice(1) }] : []
      }),
    }))
    .filter((g) => g.entries.length > 0)
  const placed = new Set(placedReportKeys())
  const extra = catalog.filter((r) => !placed.has(r.key))
  if (extra.length) {
    const other: ReportGroup = {
      id: 'other', name: 'Other reports', blurb: 'Reports that are not in a group yet', icon: FileSpreadsheet, entries: [],
    }
    out.push({
      group: other,
      entries: extra.map((r) => {
        const t = rep(r.key, r.label)
        return { entry: { id: r.key, label: r.label, blurb: r.description, targets: [t] }, main: t, also: [] }
      }),
    })
  }
  return out
}
