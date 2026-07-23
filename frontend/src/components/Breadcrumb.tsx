import { Link, useLocation } from 'react-router-dom'
import { ChevronRight, Home } from 'lucide-react'

// Maps every known path segment or full path to a readable label.
// Checked longest-match first so "/accounting/coa" beats "/accounting".
const ROUTE_LABELS: Record<string, string> = {
  // ── Full paths (checked first) ────────────────────────────────────────────
  '/dashboard':                   'Dashboard',
  '/inventory/products':          'Products',
  '/inventory/stock':             'Stock Levels',
  '/inventory/warehouses':        'Locations',
  '/inventory/batches':           'Batches & Lots',
  '/sales':                       'Invoices',
  '/sales/new':                   'New Sale',
  '/quotes':                      'Quotes',
  '/recurring':                   'Recurring Invoices',
  '/purchases':                   'Purchase Orders',
  '/bills':                       'Bills (AP)',
  '/bills/folders':               'Bill Folders',
  '/suppliers':                   'Suppliers',
  '/customers':                   'Customers',
  '/credits':                     'Credits',
  '/accounting/coa':              'Chart of Accounts',
  '/accounting/journal':          'Journal Entries',
  '/accounting/general-ledger':   'General Ledger',
  '/accounting/assets':           'Fixed Assets',
  '/accounting/reconciliation':   'Bank Reconciliation',
  '/payroll/employees':           'Employees',
  '/payroll/runs':                'Payroll Runs',
  '/expenses':                    'Income & Expenses',
  '/budgets':                     'Budgets',
  '/reports':                     'Reports',
  '/reports/balance-sheet':       'Balance Sheet',
  '/owner-analytics':             'Owner Analytics',
  '/tax':                         'Tax',
  '/audit-log':                   'Audit Log',
  '/settings':                    'Settings',
  '/billing':                     'Billing & Plans',
  '/platform-admin':              'Platform Admin',

  // ── Parent segment labels (used to build crumb trail) ────────────────────
  'inventory':   'Inventory',
  'sales':       'Sales',
  'accounting':  'Accounting',
  'payroll':     'Payroll',
  'reports':     'Reports',
  'bills':       'Procurement',
  'purchases':   'Procurement',
  'suppliers':   'Procurement',
}

// Groups a path's parent segment into a logical section label
const SECTION_MAP: Record<string, string> = {
  inventory:  'Inventory',
  sales:      'Sales',
  accounting: 'Accounting',
  payroll:    'Payroll',
  reports:    'Reports',
  bills:      'Procurement',
  purchases:  'Procurement',
  suppliers:  'Procurement',
  budgets:    'Cash Flow',
  expenses:   'Cash Flow',
}

interface Crumb {
  label: string
  href: string
}

function buildCrumbs(pathname: string): Crumb[] {
  // Always start with Home
  const crumbs: Crumb[] = [{ label: 'Home', href: '/dashboard' }]

  // Dashboard itself needs no further crumbs
  if (pathname === '/dashboard' || pathname === '/') return crumbs

  // Try full-path label first
  const pageLabel = ROUTE_LABELS[pathname]

  // Determine section from first segment
  const segments = pathname.replace(/^\//, '').split('/')
  const firstSeg = segments[0]
  const section = SECTION_MAP[firstSeg]

  if (section) {
    // Add section crumb only when there's a sub-page (e.g. /inventory/stock)
    // and the section is different from the page itself
    const sectionHref = `/${firstSeg}`
    if (segments.length > 1) {
      crumbs.push({ label: section, href: sectionHref })
    } else {
      // Single segment that belongs to a section — just show the section
      crumbs.push({ label: pageLabel ?? section, href: pathname })
      return crumbs
    }
  }

  // Add the final page crumb
  if (pageLabel) {
    crumbs.push({ label: pageLabel, href: pathname })
  }

  return crumbs
}

export default function Breadcrumb() {
  const { pathname } = useLocation()
  const crumbs = buildCrumbs(pathname)

  // Single-crumb (Home only) — nothing useful to show
  if (crumbs.length <= 1) return null

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-slate-500 select-none min-w-0">
      {crumbs.map((crumb, i) => {
        const isLast = i === crumbs.length - 1
        return (
          <span key={crumb.href} className="flex items-center gap-1 min-w-0">
            {i === 0 ? (
              <Link
                to={crumb.href}
                className="flex items-center gap-1 text-slate-500 hover:text-slate-300 transition-colors shrink-0"
                aria-label="Home"
              >
                <Home size={12} />
              </Link>
            ) : isLast ? (
              <span className="text-slate-200 font-medium truncate">{crumb.label}</span>
            ) : (
              <Link
                to={crumb.href}
                className="text-slate-500 hover:text-slate-300 transition-colors truncate"
              >
                {crumb.label}
              </Link>
            )}
            {!isLast && <ChevronRight size={11} className="text-slate-600 shrink-0" />}
          </span>
        )
      })}
    </nav>
  )
}
