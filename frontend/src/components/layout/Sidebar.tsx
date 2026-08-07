import { useEffect, useState } from 'react'
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, Package, Boxes, Layers,
  Users, Receipt, BarChart3, LogOut, X, FileText, RefreshCw,
  CreditCard, Truck, Building2, Warehouse, Calculator, BookOpen,
  BookMarked, Landmark, UsersRound, Banknote, ArrowDownCircle,
  PieChart, Scale, Shield, ClipboardList, ChevronDown, ChevronRight, ShieldCheck,
  MapPin, ClipboardCheck, GraduationCap, Briefcase, ShoppingCart,
  User, Layout, Mail, Lock, Bot, Globe, Upload, GitBranch,
  ChevronLeft, HelpCircle, LayoutGrid, Zap, Wallet, Store,
  CalendarDays,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'
import { cn } from '@/lib/utils'
import { FEATURES } from '@/lib/featureFlags'
import { CATEGORY_ORDER } from '@/lib/reportCategories'
import { useReportCatalog } from '@/hooks/useReportCatalog'
import type { ModuleKey } from '@/types'

// ─── Navigation structure ─────────────────────────────────────────────────────
// `module` maps to ModuleKey for permission filtering; null = always visible
// `ownerOnly` = only owners/admins see this item (no sub-account access)
export const navGroups: { label: string | null; alwaysGroup?: boolean; items: { name: string; href: string; icon: React.ElementType; module?: ModuleKey; ownerOnly?: boolean; partnerOnly?: boolean; businessType?: string }[] }[] = [
  {
    label: null,
    items: [
      { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
      { name: 'Partner Dashboard', href: '/partner', icon: GraduationCap, ownerOnly: true, partnerOnly: true },
      { name: 'Partner Invoices', href: '/partner/invoices', icon: Briefcase, ownerOnly: true, partnerOnly: true },
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
      { name: 'Integrations', href: '/integrations', icon: Globe, ownerOnly: true },
    ],
  },
  {
    label: 'HELP DESK',
    items: [
      { name: 'Tickets', href: '/helpdesk', icon: HelpCircle, ownerOnly: true },
    ],
  },
  // NOTE: no ANALYTICS group here — Owner Analytics is rendered by the dedicated
  // owner-only section further down (under the OWNER heading). Adding it here too
  // produced two "Owners Analytics" entries in the sidebar.
]

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
    { id: 'invoice_templates', label: 'Templates',         icon: Layout,     group: 'WORKSPACE',     ownerOnly: true },
    { id: 'team',              label: 'Team',              icon: UsersRound, group: 'WORKSPACE',     ownerOnly: true, partnerRestricted: true },
    { id: 'access',            label: 'Accountant Access', icon: ShieldCheck,group: 'WORKSPACE',     ownerOnly: true, partnerRestricted: true },
    { id: 'email',             label: 'Email',             icon: Mail,       group: 'COMMUNICATIONS',ownerOnly: true },
    { id: 'bank',              label: 'Banking',           icon: Landmark,   group: 'FINANCE',       ownerOnly: true },
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

  return (
    <aside
      data-mini={mini ? 'true' : 'false'}
      className={cn(
        'fixed inset-y-0 left-0 z-30 w-64 flex flex-col',
        mini && 'lg:w-[76px]',
        'bg-surface-900 border-r border-surface-700',
        'transition-transform duration-300 ease-in-out',
        'lg:relative lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      {/* Logo */}
      <div className={cn('flex items-center justify-between py-4 border-b border-surface-700 shrink-0', mini ? 'lg:px-2 lg:justify-center px-5' : 'px-5')}>
        <img src={mini ? '/audity-icon-dark.svg' : '/audity-logo-dark.svg'} alt="Audity" className={mini ? 'h-8 w-8 rounded-lg hidden lg:block' : 'h-9 w-auto'} draggable={false} />
        {mini && <img src="/audity-logo-dark.svg" alt="Audity" className="h-9 w-auto lg:hidden" draggable={false} />}
        <button onClick={onClose} className="lg:hidden btn-ghost p-1">
          <X size={18} />
        </button>
      </div>

      {/* Desktop collapse/expand toggle */}
      <button
        onClick={toggleMini}
        title={mini ? 'Expand sidebar' : 'Collapse sidebar'}
        className="hidden lg:flex items-center justify-center gap-2 mx-3 mt-2 py-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-surface-700/50 transition-colors text-xs shrink-0"
      >
        {mini ? <ChevronRight size={15} /> : <><ChevronLeft size={15} /><span>Collapse</span></>}
      </button>

      {/* Org badge */}
      {organisation && (
        <div className="side-mini-hide mx-3 mt-3 px-3 py-2 rounded-xl shrink-0 border bg-brand-500/10 border-brand-500/20">
          <div className="flex items-center gap-1.5">
            <p className="text-xs text-slate-400 truncate flex-1">{organisation.name}</p>
            {FEATURES.PARTNER_CHANNEL && organisation.managing_firm_name && (
              <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 shrink-0 uppercase tracking-wide">CLIENT</span>
            )}
          </div>
          <p className="text-xs font-mono text-brand-400">{organisation.currency}</p>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
        {navGroups.map((group, gi) => {
          const isCollapsed = group.label ? (collapsed[group.label] ?? false) : false
          const visibleItems = group.items.filter((item) => canSeeItem(item.module, item.ownerOnly, item.partnerOnly, item.businessType))
          if (group.label && visibleItems.length === 0) return null

          // Single-item labeled groups normally render as a plain NavLink (no
          // collapsible toggle). Groups flagged `alwaysGroup` keep their heading
          // even with one item, so a module like Cashflow reads as a module
          // rather than a loose link.
          if (group.label && visibleItems.length === 1 && !group.alwaysGroup) {
            const item = visibleItems[0]
            const isLocked = billingOnly && item.href !== '/billing'
            return (
              <div key={gi} className="pt-2">
                {isLocked ? (
                  <span className="sidebar-item opacity-30 cursor-not-allowed pointer-events-none select-none">
                    <item.icon size={16} className="shrink-0" />
                    <span className="truncate">{item.name}</span>
                  </span>
                ) : (
                  <NavLink
                    to={item.href}
                    title={item.name}
                    className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item'}
                  >
                    <item.icon size={16} className="shrink-0" />
                    <span className="truncate">{item.name}</span>
                  </NavLink>
                )}
              </div>
            )
          }

          return (
            <div key={gi}>
              {group.label && (
                <button
                  onClick={() => !billingOnly && toggleGroup(group.label!)}
                  className="side-mini-hide w-full flex items-center justify-between px-3 pt-4 pb-1 text-left group"
                >
                  <span className={cn('text-[10px] font-semibold uppercase tracking-widest group-hover:text-slate-300 transition-colors', billingOnly ? 'text-slate-600' : 'text-slate-400')}>
                    {group.label}
                  </span>
                  {!billingOnly && (isCollapsed
                    ? <ChevronRight size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
                    : <ChevronDown size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
                  )}
                </button>
              )}
              {!isCollapsed && visibleItems.map((item) => {
                const isLocked = billingOnly && item.href !== '/billing'
                return isLocked ? (
                  <span key={item.href} className="sidebar-item opacity-30 cursor-not-allowed pointer-events-none select-none">
                    <item.icon size={16} className="shrink-0" />
                    <span className="truncate">{item.name}</span>
                  </span>
                ) : (
                  <NavLink
                    key={item.href}
                    to={item.href}
                    title={item.name}
                    end={item.href === '/sales'}
                    className={({ isActive }) =>
                      isActive ? 'sidebar-item-active' : 'sidebar-item'
                    }
                  >
                    <item.icon size={16} className="shrink-0" />
                    <span className="truncate">{item.name}</span>
                  </NavLink>
                )
              })}
            </div>
          )
        })}

        {/* GENERAL REPORTS sub-nav — fixed links to the dedicated report
            pages, then a fetched, collapsible category tree mirroring
            AllReportsPage.tsx's "General Reports" hub (/reports/all), same
            two-level pattern as the SETTINGS sub-nav below. */}
        {!billingOnly && canSeeItem('reports') && (
          <div>
            <button
              onClick={() => setReportsOpen((v) => !v)}
              className="side-mini-hide w-full flex items-center justify-between px-3 pt-4 pb-1 text-left group"
            >
              <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 group-hover:text-slate-300 transition-colors">
                GENERAL REPORTS
              </span>
              {reportsOpen
                ? <ChevronDown size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
                : <ChevronRight size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
              }
            </button>

            {reportsOpen && !mini && (
              <>
                {/* Fixed links to the dedicated, richer report pages. */}
                {REPORTS_FIXED_LINKS
                  .filter((item) => canSeeItem(item.module))
                  .map((item) => (
                    <NavLink
                      key={item.href}
                      to={item.href}
                      end={item.href === '/reports/all'}
                      title={item.name}
                      className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item'}
                    >
                      <item.icon size={16} className="shrink-0" />
                      <span className="truncate">{item.name}</span>
                    </NavLink>
                  ))}

                {/* Fetched category tree — every report in the registry,
                    grouped exactly like the All Reports page. */}
                {reportsGrouped.map((cat) => {
                  const isGroupOpen = reportGroupsOpen[cat.name] ?? false
                  return (
                    <div key={cat.name} className="pl-2">
                      <button
                        onClick={() => toggleReportGroup(cat.name)}
                        className="w-full flex items-center justify-between px-2 py-1.5 text-left group/rg rounded-lg hover:bg-surface-700/40 transition-colors"
                      >
                        <span className="flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-widest text-slate-500 group-hover/rg:text-slate-400 transition-colors">
                          <cat.icon size={11} className="shrink-0" />
                          {cat.name}
                        </span>
                        {isGroupOpen
                          ? <ChevronDown size={10} className="text-slate-600 group-hover/rg:text-slate-400 transition-colors" />
                          : <ChevronRight size={10} className="text-slate-600 group-hover/rg:text-slate-400 transition-colors" />
                        }
                      </button>

                      {isGroupOpen && cat.reports.map((r) => {
                        const isActive = activeReportKey === r.key
                        return (
                          <Link
                            key={r.key}
                            to={`/reports/all?report=${r.key}`}
                            title={r.description}
                            className={cn(
                              'flex items-center gap-2.5 pl-4 pr-3 py-2 rounded-xl text-sm transition-colors',
                              isActive
                                ? 'bg-brand-500/15 text-brand-300 font-medium border-l-2 border-brand-500 ml-1'
                                : 'text-slate-400 hover:text-slate-200 hover:bg-surface-700/50 ml-1',
                            )}
                          >
                            <span className="truncate">{r.label}</span>
                          </Link>
                        )
                      })}
                    </div>
                  )
                })}
              </>
            )}
          </div>
        )}

        {/* Owner-only analytics — hidden in billing-only mode */}
        {!billingOnly && isOwnerOrAdmin && canSeeItem('owner_analytics') && (
          <div>
            <div className="side-mini-hide px-3 pt-4 pb-1">
              <span className="text-[10px] font-semibold text-brand-600 uppercase tracking-widest">OWNER</span>
            </div>
            <NavLink
              to="/owner-analytics"
              className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item'}
            >
              <ShieldCheck size={16} className="shrink-0 text-brand-400" />
              <span className="truncate text-brand-400">Owner Analytics</span>
            </NavLink>
          </div>
        )}

        {/* Settings sub-nav — collapsible with sub-groups */}
        {!billingOnly && (
          <div>
            {/* Top-level SETTINGS toggle */}
            <button
              onClick={() => setSettingsOpen((v) => !v)}
              className="side-mini-hide w-full flex items-center justify-between px-3 pt-4 pb-1 text-left group"
            >
              <span className={cn('text-[10px] font-semibold uppercase tracking-widest group-hover:text-slate-300 transition-colors', pathname === '/settings' ? 'text-brand-400' : 'text-slate-400')}>
                SETTINGS
              </span>
              {settingsOpen
                ? <ChevronDown size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
                : <ChevronRight size={12} className="text-slate-400 group-hover:text-slate-300 transition-colors" />
              }
            </button>

            {/* Sub-groups */}
            {settingsOpen && !mini && SETTINGS_GROUPS.map((groupLabel) => {
              const groupTabs = visibleSettingsTabs.filter((t) => t.group === groupLabel)
              if (groupTabs.length === 0) return null
              const isGroupOpen = settingsGroupsOpen[groupLabel] ?? false
              return (
                <div key={groupLabel} className="pl-2">
                  {/* Sub-group header */}
                  <button
                    onClick={() => toggleSettingsGroup(groupLabel)}
                    className="w-full flex items-center justify-between px-2 py-1.5 text-left group/sg rounded-lg hover:bg-surface-700/40 transition-colors"
                  >
                    <span className="text-[9px] font-semibold uppercase tracking-widest text-slate-500 group-hover/sg:text-slate-400 transition-colors">
                      {groupLabel}
                    </span>
                    {isGroupOpen
                      ? <ChevronDown size={10} className="text-slate-600 group-hover/sg:text-slate-400 transition-colors" />
                      : <ChevronRight size={10} className="text-slate-600 group-hover/sg:text-slate-400 transition-colors" />
                    }
                  </button>

                  {/* Sub-group items */}
                  {isGroupOpen && groupTabs.map((t) => {
                    const isActive = pathname === '/settings' && activeSettingsTab === t.id
                    return (
                      <Link
                        key={t.id}
                        to={`/settings?tab=${t.id}`}
                        className={cn(
                          'flex items-center gap-2.5 pl-4 pr-3 py-2 rounded-xl text-sm transition-colors',
                          isActive
                            ? 'bg-brand-500/15 text-brand-300 font-medium border-l-2 border-brand-500 ml-1'
                            : 'text-slate-400 hover:text-slate-200 hover:bg-surface-700/50 ml-1',
                        )}
                      >
                        <t.icon size={14} className="shrink-0" />
                        <span className="truncate">{t.label}</span>
                      </Link>
                    )
                  })}
                </div>
              )
            })}
          </div>
        )}
      </nav>

      {/* Settings + User + Logout */}
      <div className="border-t border-surface-700 p-3 space-y-1 shrink-0">
        {/* Platform admin link — only for superusers */}
        {user?.is_superuser && (
          <NavLink
            to="/platform-admin"
            className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item'}
          >
            <Shield size={16} className="shrink-0 text-red-400" />
            <span className="text-red-400">Platform Admin</span>
          </NavLink>
        )}
        <button
          onClick={() => navigate('/settings')}
          className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-surface-700/50 rounded-xl transition-colors"
        >
          <div className="w-8 h-8 bg-brand-500 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0">
            {user?.first_name?.[0]}{user?.last_name?.[0]}
          </div>
          <div className="side-mini-hide min-w-0 text-left">
            <p className="text-sm font-medium text-white truncate">
              {user?.first_name} {user?.last_name}
            </p>
            <p className="text-xs text-slate-500 truncate">{user?.email}</p>
          </div>
        </button>

        <button onClick={handleLogout} className="sidebar-item w-full text-red-400 hover:text-red-300 hover:bg-red-500/10">
          <LogOut size={16} />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  )
}
