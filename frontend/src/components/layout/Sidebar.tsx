import { useEffect, useState } from 'react'
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom'
import {
  Package, Boxes, Layers,
  Users, Receipt, BarChart3, X, FileText, RefreshCw,
  CreditCard, Truck, Building2, Warehouse, Calculator, BookOpen,
  BookMarked, Landmark, UsersRound, Banknote, ArrowDownCircle,
  PieChart, Scale, Shield, ClipboardList, ChevronDown, ChevronRight, ShieldCheck,
  MapPin, ClipboardCheck, GraduationCap, ShoppingCart,
  User, Layout, Mail, Lock, Bot, Globe, Upload, GitBranch,
  ChevronLeft, LayoutGrid, Zap, Wallet, Store,
  CalendarDays, Bell, RotateCcw,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'
import { cn } from '@/lib/utils'
import { FEATURES } from '@/lib/featureFlags'
import { CATEGORY_ORDER } from '@/lib/reportCategories'
import { useReportCatalog } from '@/hooks/useReportCatalog'
import type { ModuleKey } from '@/types'
import '@/styles/app-shell.css'
import { DesignerIcon, type DesignerIconName } from '@/assets/designer-icons'

/** Wraps a designer icon so it can sit in the nav data like a lucide icon. */
const di = (name: DesignerIconName): React.ElementType =>
  function DI({ size, className }: { size?: number; className?: string }) {
    return <DesignerIcon name={name} size={size} className={className} />
  }
const ICON = {
  dashboard: di('dashboard'), partnerInvoices: di('partner-invoices'), accounting: di('accounting'),
  customers: di('customers'), procurement: di('procurement'), inventory: di('inventory'), hr: di('hr'),
  reports: di('reports'), incomeExpenses: di('income-expenses'), compliance: di('compliance'),
  billing: di('billing'), tickets: di('tickets'), analytics: di('analytics'), settings: di('settings'),
  signOut: di('sign-out'),
}

// ─── Navigation structure ─────────────────────────────────────────────────────
// `module` maps to ModuleKey for permission filtering; null = always visible
// `ownerOnly` = only owners/admins see this item (no sub-account access)
export const navGroups: { label: string | null; alwaysGroup?: boolean; items: { name: string; href: string; icon: React.ElementType; module?: ModuleKey; ownerOnly?: boolean; partnerOnly?: boolean; businessType?: string }[] }[] = [
  {
    label: null,
    items: [
      { name: 'Dashboard', href: '/dashboard', icon: ICON.dashboard },
      { name: 'Partner Dashboard', href: '/partner', icon: GraduationCap, ownerOnly: true, partnerOnly: true },
      { name: 'Partner Invoices', href: '/partner/invoices', icon: ICON.partnerInvoices, ownerOnly: true, partnerOnly: true },
    ],
  },
  {
    // Accountant-first ordering (Sage/QuickBooks/Xero style): the ledger comes first.
    label: 'ACCOUNTING & FINANCE',
    items: [
      { name: 'Chart of Accounts', href: '/accounting/coa', icon: BookOpen, module: 'accounting' },
      { name: 'Beginning Balances', href: '/accounting/beginning-balances', icon: Scale, module: 'accounting' },
      { name: 'Journal Entries', href: '/accounting/journal', icon: BookMarked, module: 'accounting' },
      { name: 'Budgets', href: '/budgets', icon: PieChart, module: 'budget' },
      { name: 'Budget Periods', href: '/budgets/periods', icon: CalendarDays, module: 'budget' },
      { name: 'Budget Allocations', href: '/budgets/allocations', icon: Wallet, module: 'budget' },
      { name: 'Fixed Assets', href: '/accounting/assets', icon: Landmark, module: 'accounting' },
      { name: 'Bank Reconciliation', href: '/accounting/reconciliation', icon: Scale, module: 'accounting' },
      { name: 'GL Health', href: '/accounting/gl-health', icon: ShieldCheck, module: 'accounting' },
    ],
  },
  {
    label: 'CUSTOMERS & RECEIPTS',
    items: [
      { name: 'Customers', href: '/customers', icon: Users, module: 'customers' },
      { name: 'Customer Receipts / Deposits', href: '/credits', icon: CreditCard, module: 'customers' },
      { name: 'Transfers to Confirm', href: '/payments/transfers', icon: Banknote, module: 'sales' },
      { name: 'Card Settlement', href: '/payments/settlement', icon: CreditCard, module: 'sales' },
    ],
  },
  {
    label: 'SALES & POS',
    items: [
      { name: 'Quotes', href: '/quotes', icon: ClipboardList, module: 'quotes' },
      { name: 'Invoices', href: '/sales', icon: FileText, module: 'sales' },
      { name: 'Sales Returns', href: '/sales/returns', icon: RotateCcw, module: 'sales' },
      { name: 'Recurring Invoices', href: '/recurring', icon: RefreshCw, module: 'recurring' },
      { name: 'Register (Till)', href: '/pos/register', icon: ShoppingCart, module: 'sales' },
      { name: 'New Sale / Invoice', href: '/sales/new', icon: Receipt, module: 'sales' },
      { name: 'POS Orders', href: '/pos/restaurant', icon: ClipboardList, module: 'sales' },
      { name: 'Till / Cash-up', href: '/pos/till', icon: Wallet, module: 'sales' },
      { name: 'Tables', href: '/pos/tables', icon: LayoutGrid, module: 'sales', businessType: 'restaurant' },
      { name: 'Kitchen (KOT)', href: '/pos/kitchen', icon: ClipboardCheck, module: 'sales', businessType: 'restaurant' },
      { name: 'Storefront', href: '/storefront', icon: Store, module: 'sales' },
      { name: 'Locations', href: '/locations', icon: MapPin, module: 'sales' },
    ],
  },
  {
    label: 'PROCUREMENT',
    items: [
      { name: 'Suppliers', href: '/suppliers', icon: Building2, module: 'suppliers' },
      { name: 'Purchase Orders', href: '/purchases', icon: Truck, module: 'purchases' },
      { name: 'Purchase Returns', href: '/purchases/returns', icon: RotateCcw, module: 'purchases' },
      { name: 'Pay Bills (PO)', href: '/bills', icon: Receipt, module: 'bills' },
    ],
  },
  {
    label: 'INVENTORY',
    items: [
      { name: 'Products', href: '/inventory/products', icon: Package, module: 'inventory' },
      { name: 'Stock Levels', href: '/inventory/stock', icon: Boxes, module: 'inventory' },
      { name: 'Warehouses', href: '/inventory/warehouses', icon: Warehouse, module: 'inventory' },
      { name: 'Batches & Lots', href: '/inventory/batches', icon: Layers, module: 'inventory' },
    ],
  },
  {
    label: 'HR',
    items: [
      { name: 'Employees', href: '/hr/employees', icon: UsersRound, module: 'payroll' },
      { name: 'Org Chart', href: '/hr/org-chart', icon: GitBranch, module: 'payroll' },
      { name: 'Leave', href: '/hr/leave', icon: CalendarDays, module: 'payroll' },
      { name: 'Payroll Runs', href: '/hr/runs', icon: Banknote, module: 'payroll' },
      { name: 'Compliance & Remittances', href: '/hr/compliance', icon: ShieldCheck, module: 'payroll' },
      { name: 'HR Analytics', href: '/hr/analytics', icon: BarChart3, module: 'payroll' },
    ],
  },
  {
    // Keeps its heading even though it holds one item — Cashflow is a module,
    // not a loose link (see alwaysGroup in the renderer below).
    label: 'CASHFLOW',
    alwaysGroup: true,
    items: [
      { name: 'Income & Expense', href: '/expenses', icon: ArrowDownCircle, module: 'expenses' },
    ],
  },
  // NOTE: "GENERAL REPORTS" used to be a plain navGroups entry here (a flat
  // list of 6 links). It's now rendered as its own bespoke block below (see
  // REPORTS_FIXED_LINKS + the "Reports sub-nav" section near the Settings
  // sub-nav), because it needs a two-level category tree the generic
  // navGroups renderer doesn't support — the same reason Settings gets its
  // own bespoke block instead of living in this array.
  {
    label: 'COMPLIANCE',
    items: [
      { name: 'Tax', href: '/tax', icon: Calculator, module: 'tax' },
      { name: 'Audit Log', href: '/audit-log', icon: Shield, module: 'audit_log', ownerOnly: true },
    ],
  },
  {
    label: 'BILLING & PLANS',
    items: [
      { name: 'Current Plan', href: '/billing#current-plan', icon: CreditCard, ownerOnly: true },
      { name: 'Change Plan', href: '/billing#plans-section', icon: Zap, ownerOnly: true },
      { name: 'Billing & Invoices', href: '/billing#payment-history', icon: Receipt, ownerOnly: true },
      // Replaces the old "Integrations" (raw webhooks + Zapier) nav entry —
      // that page still exists and its route still works (see App.tsx),
      // it's just no longer linked from anywhere in the default nav. This
      // is a deliberate product decision, not an oversight: one existing
      // paying customer (McEva International) reaches it via a direct URL
      // from support instead.
      { name: 'Connectors', href: '/connectors', icon: Globe, ownerOnly: true },
    ],
  },
  {
    label: 'HELP DESK',
    items: [
      { name: 'Tickets', href: '/helpdesk', icon: ICON.tickets, ownerOnly: true },
    ],
  },
  // NOTE: no ANALYTICS group here — Owner Analytics is rendered by the dedicated
  // owner-only section further down (under the OWNER heading). Adding it here too
  // produced two "Owners Analytics" entries in the sidebar.
]

// Display names and row icons for the group headers. The `label` strings in
// navGroups stay as they are (they are state keys and what the command palette
// groups by); only what the sidebar shows changes.
const GROUP_TITLES: Record<string, string> = {
  'ACCOUNTING & FINANCE': 'Accounting & Finance',
  'CUSTOMERS & RECEIPTS': 'Customers & Receipts',
  'SALES & POS': 'Sales & POS',
  'PROCUREMENT': 'Procurement',
  'INVENTORY': 'Inventory',
  'HR': 'HR',
  'CASHFLOW': 'Cashflow',
  'COMPLIANCE': 'Compliance',
  'BILLING & PLANS': 'Billing & Plans',
  'HELP DESK': 'Help Desk',
}
const GROUP_ICONS: Record<string, React.ElementType> = {
  'ACCOUNTING & FINANCE': ICON.accounting,
  'CUSTOMERS & RECEIPTS': ICON.customers,
  'SALES & POS': ShoppingCart, // the designer's pack has no Sales & POS icon
  'PROCUREMENT': ICON.procurement,
  'INVENTORY': ICON.inventory,
  'HR': ICON.hr,
  'CASHFLOW': ICON.incomeExpenses,
  'COMPLIANCE': ICON.compliance,
  'BILLING & PLANS': ICON.billing,
  'HELP DESK': ICON.tickets,
}

// The "GENERAL REPORTS" section's fixed links — these are separate, richer
// pages (charts, drill-down, dedicated layouts) rather than registry entries,
// so they stay as plain links above the fetched category tree instead of
// being replaced by it. (Sales By Customer/Product and Balance Sheet all have
// a same-named counterpart inside the registry tree too — that's expected;
// the tree entry runs the generic report engine, these links open the
// purpose-built page for that report.)
const REPORTS_FIXED_LINKS: { name: string; href: string; icon: React.ElementType; module?: ModuleKey }[] = [
  { name: 'All Reports', href: '/reports/all', icon: BookMarked, module: 'reports' },
  { name: 'Financial Statements', href: '/reports', icon: BarChart3, module: 'reports' },
  { name: 'Balance Sheet', href: '/reports/balance-sheet', icon: Scale, module: 'accounting' },
  { name: 'Stock Reports', href: '/reports/stock', icon: ClipboardCheck, module: 'inventory' },
  { name: 'Sales by Customer', href: '/reports/sales-by-customer', icon: Users, module: 'reports' },
  { name: 'Sales by Product', href: '/reports/sales-by-product', icon: ShoppingCart, module: 'reports' },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
  billingOnly?: boolean
}

export default function Sidebar({ open, onClose, billingOnly = false }: SidebarProps) {
  const { user, organisation, tokens, logout, memberRole, modulePermissions, planModules, planName } = useAuthStore()
  const navigate = useNavigate()

  // null = membership not yet loaded; treat as restricted (not full access) until confirmed
  const isOwnerOrAdmin = user?.is_superuser === true || memberRole === 'owner' || memberRole === 'admin'
  const { pathname, search } = useLocation()

  // Returns true if the nav item should be visible.
  // Checks: ownerOnly → plan modules → sub-account RBAC permissions
  const canSeeItem = (mod?: ModuleKey, ownerOnly?: boolean, partnerOnly?: boolean, businessType?: string) => {
    const membershipLoading = memberRole === null && !user?.is_superuser
    if (partnerOnly && (!FEATURES.PARTNER_CHANNEL || !user?.has_partner_profile)) return false
    if (partnerOnly && !user?.is_superuser && !planName?.startsWith('partner')) return false
    // Business-type gate (e.g. restaurant-only POS): hide once the org's type is known
    // and differs. Fail-open while the org type is still loading.
    const orgBusinessType = (organisation as { business_type?: string } | null)?.business_type
    if (businessType && orgBusinessType && orgBusinessType !== businessType) return false
    if (!mod) return true                             // no module restriction (dashboard, settings)
    if (user?.is_superuser) return true              // superusers always see everything
    // Plan-level gate: if the active plan restricts modules, only show allowed ones
    if (planModules !== null && !planModules.includes(mod)) return false
    // While membership is loading, hide all module items — sub-accounts must not see
    // modules they have no access to, even briefly. Sub-account login now pre-loads
    // membership in the response so this window is typically zero for staff logins.
    if (membershipLoading) return false
    if (ownerOnly && !isOwnerOrAdmin) return false   // explicitly owner-only items
    if (isOwnerOrAdmin) return true                   // owners/admins see all plan-allowed modules
    const level = modulePermissions?.[mod]
    return level === 'view' || level === 'write' || level === 'edit'
  }

  // Track which groups are collapsed.
  // A group starts collapsed only if it contains no active route.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    navGroups.forEach((group) => {
      if (!group.label) return
      const hasActive = group.items.some((item) => pathname.startsWith(item.href))
      init[group.label] = !hasActive
    })
    return init
  })

  const toggleGroup = (label: string) => {
    setCollapsed((prev) => ({ ...prev, [label]: !prev[label] }))
  }

  const handleLogout = async () => {
    try {
      if (tokens?.refresh) await authApi.logout(tokens.refresh)
    } finally {
      logout()
      navigate('/login')
    }
  }

  const activeSettingsTab = new URLSearchParams(search).get('tab') ?? 'profile'
  const isPartnerAccountant = memberRole === 'accountant' && !user?.is_superuser
  const hasSettingsPerm = isOwnerOrAdmin || (modulePermissions?.['settings'] ?? 'none') !== 'none'

  type SettingsTabDef = {
    id: string; label: string; icon: React.ElementType
    ownerOnly?: boolean; partnerRestricted?: boolean
    requiresSettings?: boolean; requiresPlan?: string
    group: string
  }
  const settingsTabs: SettingsTabDef[] = [
    { id: 'profile',           label: 'Profile',           icon: User,       group: 'ACCOUNT' },
    { id: 'security',          label: 'Security',          icon: Shield,     group: 'ACCOUNT',       partnerRestricted: true },
    { id: 'notifications',     label: 'Notifications',     icon: Bell,       group: 'ACCOUNT' },
    { id: 'invoice_templates', label: 'Templates',         icon: Layout,     group: 'WORKSPACE',     ownerOnly: true },
    { id: 'team',              label: 'Team',              icon: UsersRound, group: 'WORKSPACE',     ownerOnly: true, partnerRestricted: true },
    { id: 'access',            label: 'Accountant Access', icon: ShieldCheck,group: 'WORKSPACE',     ownerOnly: true, partnerRestricted: true },
    { id: 'email',             label: 'Email',             icon: Mail,       group: 'COMMUNICATIONS',ownerOnly: true },
    { id: 'bank',              label: 'Banking',           icon: Landmark,   group: 'FINANCE',       ownerOnly: true },
    // Where a merchant enters their OWN gateway keys. Without this entry the
    // tab is only reachable by typing the URL, which is how collecting
    // payments stayed unfixable from inside the app.
    { id: 'payments',          label: 'Payments',          icon: CreditCard, group: 'FINANCE',       ownerOnly: true },
    { id: 'gl_mapping',        label: 'GL Mapping',        icon: GitBranch,  group: 'FINANCE',       requiresSettings: true, requiresPlan: 'accounting' },
    { id: 'periods',           label: 'Periods',           icon: Lock,       group: 'FINANCE',       requiresSettings: true, requiresPlan: 'accounting' },
    { id: 'ai',                label: 'AI',                icon: Bot,        group: 'ADVANCED',      ownerOnly: true },
    { id: 'whitelabel',        label: 'White-label',       icon: Globe,      group: 'ADVANCED',      ownerOnly: true },
    { id: 'import',            label: 'Migration',         icon: Upload,     group: 'ADVANCED',      requiresSettings: true },
  ]
  const SETTINGS_GROUPS = ['ACCOUNT', 'WORKSPACE', 'COMMUNICATIONS', 'FINANCE', 'ADVANCED']

  const visibleSettingsTabs = settingsTabs.filter((t) => {
    if (t.partnerRestricted && isPartnerAccountant) return false
    if (t.ownerOnly && !isOwnerOrAdmin) return false
    if (t.requiresSettings && !hasSettingsPerm) return false
    if (t.requiresPlan && planModules !== null && !planModules.includes(t.requiresPlan) && !user?.is_superuser) return false
    return true
  })

  // ─── Mini (collapsed) sidebar — desktop only, persisted ────────────────────
  const [mini, setMini] = useState<boolean>(() => {
    try { return localStorage.getItem('audity-sidebar-mini') === '1' } catch { return false }
  })
  const toggleMini = () => setMini((v) => {
    const next = !v
    try { localStorage.setItem('audity-sidebar-mini', next ? '1' : '0') } catch { /* ignore */ }
    return next
  })

  const [settingsOpen, setSettingsOpen] = useState(() => pathname === '/settings')
  const [settingsGroupsOpen, setSettingsGroupsOpen] = useState<Record<string, boolean>>(() => {
    // auto-expand the group that contains the current active tab
    const activeGroup = settingsTabs.find((t) => t.id === (new URLSearchParams(search).get('tab') ?? 'profile'))?.group ?? 'ACCOUNT'
    return Object.fromEntries(SETTINGS_GROUPS.map((g) => [g, g === activeGroup]))
  })
  const toggleSettingsGroup = (g: string) =>
    setSettingsGroupsOpen((prev) => ({ ...prev, [g]: !prev[g] }))

  // ─── Reports sub-nav — same collapsible-tree pattern as Settings above ────
  const { catalog: reportCatalog } = useReportCatalog()
  const activeReportKey = pathname === '/reports/all' ? new URLSearchParams(search).get('report') : null
  const reportsGrouped = CATEGORY_ORDER
    .map((c) => ({ ...c, reports: reportCatalog.filter((r) => r.category === c.name) }))
    .filter((c) => c.reports.length > 0)

  const [reportsOpen, setReportsOpen] = useState(() => pathname.startsWith('/reports'))
  const [reportGroupsOpen, setReportGroupsOpen] = useState<Record<string, boolean>>({})
  const toggleReportGroup = (g: string) =>
    setReportGroupsOpen((prev) => ({ ...prev, [g]: !prev[g] }))
  // Auto-expand whichever category holds the currently-selected report, once
  // the catalog has loaded enough to know which category that is. Runs after
  // the catalog fetch resolves (reportsGrouped is empty until then), so a
  // sidebar link click that lands on /reports/all?report=<key> reveals its
  // own category instead of requiring the user to hunt for it.
  useEffect(() => {
    if (!activeReportKey || reportsGrouped.length === 0) return
    const activeGroup = reportsGrouped.find((c) => c.reports.some((r) => r.key === activeReportKey))?.name
    if (activeGroup) setReportGroupsOpen((prev) => (prev[activeGroup] ? prev : { ...prev, [activeGroup]: true }))
  }, [activeReportKey, reportsGrouped.length])

  const rowClass = (isActive: boolean) => cn('sh-row', isActive && 'sh-row-on')

  return (
    <aside
      data-mini={mini ? 'true' : 'false'}
      className={cn(
        'sh-aside fixed inset-y-0 left-0 z-30 flex flex-col w-[var(--sh-side-w)]',
        mini && 'lg:w-[76px]',
        'transition-transform duration-300 ease-in-out',
        'lg:relative lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      {/* Mobile close (the logo now lives in the top bar) */}
      <button onClick={onClose} aria-label="Close menu" className="sh-icon-btn lg:hidden self-end m-2 shrink-0">
        <X size={20} />
      </button>

      {/* Org badge */}
      {organisation && (
        <div className="side-mini-hide sh-org shrink-0">
          <div className="flex items-center gap-1.5">
            <p className="flex-1">{organisation.name}</p>
            {FEATURES.PARTNER_CHANNEL && organisation.managing_firm_name && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-500 shrink-0 uppercase tracking-wide">CLIENT</span>
            )}
          </div>
          <p>{organisation.currency}</p>
        </div>
      )}

      {/* Nav */}
      <nav className="sh-nav">
        {navGroups.map((group, gi) => {
          const isCollapsed = group.label ? (collapsed[group.label] ?? false) : false
          const visibleItems = group.items.filter((item) => canSeeItem(item.module, item.ownerOnly, item.partnerOnly, item.businessType))
          if (group.label && visibleItems.length === 0) return null

          const renderLink = (item: typeof visibleItems[number], withCollapse = false) => {
            const isLocked = billingOnly && item.href !== '/billing'
            const node = isLocked ? (
              <span key={item.href} className="sh-row sh-row-locked">
                <item.icon size={20} className="sh-ico shrink-0" />
                <span className="sh-label">{item.name}</span>
              </span>
            ) : (
              <NavLink
                key={item.href}
                to={item.href}
                title={item.name}
                end={item.href === '/sales'}
                className={({ isActive }) => rowClass(isActive)}
              >
                <item.icon size={20} className="sh-ico shrink-0" />
                <span className="sh-label">{item.name}</span>
              </NavLink>
            )
            if (!withCollapse) return node
            return (
              <div key={item.href} className="relative">
                {node}
                <button
                  onClick={toggleMini}
                  title={mini ? 'Expand sidebar' : 'Collapse sidebar'}
                  aria-label={mini ? 'Expand sidebar' : 'Collapse sidebar'}
                  className="sh-collapse hidden lg:flex"
                >
                  {mini ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
                </button>
              </div>
            )
          }

          // Single-item labeled groups normally render as a plain NavLink (no
          // collapsible toggle). Groups flagged `alwaysGroup` keep their heading
          // even with one item, so a module like Cashflow reads as a module
          // rather than a loose link.
          if (group.label && visibleItems.length === 1 && !group.alwaysGroup) {
            return renderLink(visibleItems[0])
          }

          // Unlabelled first group: Dashboard (+ partner links) as top-level rows.
          if (!group.label) {
            return visibleItems.map((item, ii) => renderLink(item, gi === 0 && ii === 0))
          }

          const GroupIcon = GROUP_ICONS[group.label] ?? LayoutGrid
          return (
            <div key={gi}>
              <button
                onClick={() => !billingOnly && toggleGroup(group.label!)}
                className={cn('sh-row sh-group-head', billingOnly && 'opacity-40')}
                aria-expanded={!isCollapsed}
              >
                <GroupIcon size={20} className="sh-ico shrink-0" />
                <span className="sh-label">{GROUP_TITLES[group.label] ?? group.label}</span>
                {!billingOnly && (isCollapsed
                  ? <ChevronRight size={16} className="sh-caret" />
                  : <ChevronDown size={16} className="sh-caret" />
                )}
              </button>
              {!isCollapsed && (
                <div className="sh-sub">{visibleItems.map((item) => renderLink(item))}</div>
              )}
            </div>
          )
        })}

        {/* GENERAL REPORTS sub-nav — fixed links to the dedicated report
            pages, then a fetched, collapsible category tree mirroring
            AllReportsPage.tsx's "General Reports" hub (/reports/all), same
            two-level pattern as the SETTINGS sub-nav below. */}
        {!billingOnly && canSeeItem('reports') && (
          <div className="sh-mini-hide">
            <button
              onClick={() => setReportsOpen((v) => !v)}
              className="sh-row"
              aria-expanded={reportsOpen}
            >
              <ICON.reports size={20} className="sh-ico shrink-0" />
              <span className="sh-label">General Reports</span>
              {reportsOpen ? <ChevronDown size={16} className="sh-caret" /> : <ChevronRight size={16} className="sh-caret" />}
            </button>

            {reportsOpen && (
              <div className="sh-sub">
                {/* Fixed links to the dedicated, richer report pages. */}
                {REPORTS_FIXED_LINKS
                  .filter((item) => canSeeItem(item.module))
                  .map((item) => (
                    <NavLink
                      key={item.href}
                      to={item.href}
                      end={item.href === '/reports/all'}
                      title={item.name}
                      className={({ isActive }) => rowClass(isActive)}
                    >
                      <item.icon size={18} className="sh-ico shrink-0" />
                      <span className="sh-label">{item.name}</span>
                    </NavLink>
                  ))}

                {/* Fetched category tree — every report in the registry,
                    grouped exactly like the All Reports page. */}
                {reportsGrouped.map((cat) => {
                  const isGroupOpen = reportGroupsOpen[cat.name] ?? false
                  return (
                    <div key={cat.name}>
                      <button onClick={() => toggleReportGroup(cat.name)} className="sh-sub-head" aria-expanded={isGroupOpen}>
                        <cat.icon size={13} className="shrink-0" />
                        <span>{cat.name}</span>
                        {isGroupOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </button>

                      {isGroupOpen && cat.reports.map((r) => {
                        const isActive = activeReportKey === r.key
                        return (
                          <Link
                            key={r.key}
                            to={`/reports/all?report=${r.key}`}
                            title={r.description}
                            className={cn('sh-row', isActive && 'sh-row-on')}
                          >
                            <span className="sh-label">{r.label}</span>
                          </Link>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Owner-only analytics — hidden in billing-only mode */}
        {!billingOnly && isOwnerOrAdmin && canSeeItem('owner_analytics') && (
          <NavLink
            to="/owner-analytics"
            className={({ isActive }) => rowClass(isActive)}
          >
            <ICON.analytics size={20} className="sh-ico shrink-0" />
            <span className="sh-label">Owner Analytics</span>
          </NavLink>
        )}

        {/* Settings sub-nav — collapsible with sub-groups */}
        {!billingOnly && (
          <div className="sh-mini-hide">
            {/* Top-level SETTINGS toggle */}
            <button
              onClick={() => setSettingsOpen((v) => !v)}
              className={cn('sh-row', pathname === '/settings' && 'sh-row-on')}
              aria-expanded={settingsOpen}
            >
              <ICON.settings size={20} className="sh-ico shrink-0" />
              <span className="sh-label">Settings</span>
              {settingsOpen ? <ChevronDown size={16} className="sh-caret" /> : <ChevronRight size={16} className="sh-caret" />}
            </button>

            {/* Sub-groups */}
            {settingsOpen && (
              <div className="sh-sub">
                {SETTINGS_GROUPS.map((groupLabel) => {
                  const groupTabs = visibleSettingsTabs.filter((t) => t.group === groupLabel)
                  if (groupTabs.length === 0) return null
                  const isGroupOpen = settingsGroupsOpen[groupLabel] ?? false
                  return (
                    <div key={groupLabel}>
                      {/* Sub-group header */}
                      <button onClick={() => toggleSettingsGroup(groupLabel)} className="sh-sub-head" aria-expanded={isGroupOpen}>
                        <span>{groupLabel}</span>
                        {isGroupOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </button>

                      {/* Sub-group items */}
                      {isGroupOpen && groupTabs.map((t) => {
                        const isActive = pathname === '/settings' && activeSettingsTab === t.id
                        return (
                          <Link
                            key={t.id}
                            to={`/settings?tab=${t.id}`}
                            className={cn('sh-row', isActive && 'sh-row-on')}
                          >
                            <t.icon size={16} className="sh-ico shrink-0" />
                            <span className="sh-label">{t.label}</span>
                          </Link>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </nav>

      {/* Platform admin + Sign out */}
      <div className="sh-foot">
        {/* Platform admin link — only for superusers */}
        {user?.is_superuser && (
          <NavLink
            to="/platform-admin"
            title="Platform Admin"
            className={({ isActive }) => cn(rowClass(isActive), 'sh-row-danger')}
          >
            <Shield size={20} className="sh-ico shrink-0" />
            <span className="sh-label">Platform Admin</span>
          </NavLink>
        )}
        <button onClick={handleLogout} title="Sign out" className="sh-row sh-row-danger">
          <ICON.signOut size={20} className="sh-ico shrink-0" />
          <span className="sh-label">Sign out</span>
        </button>
      </div>
    </aside>
  )
}
