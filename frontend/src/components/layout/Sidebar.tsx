import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Package, Boxes, Plus, Layers,
  Users, Receipt, BarChart3, LogOut, X, FileText, RefreshCw,
  CreditCard, Truck, Building2, Warehouse, Calculator, BookOpen,
  BookMarked, Landmark, UsersRound, Banknote, ArrowDownCircle,
  PieChart, Scale, Shield, ClipboardList, ChevronDown, ChevronRight, ShieldCheck,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'
import { cn } from '@/lib/utils'
import type { ModuleKey } from '@/types'

// ─── Navigation structure ─────────────────────────────────────────────────────
// `module` maps to ModuleKey for permission filtering; null = always visible
// `ownerOnly` = only owners/admins see this item (no sub-account access)
const navGroups: { label: string | null; items: { name: string; href: string; icon: React.ElementType; module?: ModuleKey; ownerOnly?: boolean }[] }[] = [
  {
    label: null,
    items: [{ name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard }],
  },
  {
    label: 'INVENTORY',
    items: [
      { name: 'Products', href: '/inventory/products', icon: Package, module: 'inventory' },
      { name: 'Stock Levels', href: '/inventory/stock', icon: Boxes, module: 'inventory' },
      { name: 'Locations', href: '/inventory/warehouses', icon: Warehouse, module: 'inventory' },
      { name: 'Batches & Lots', href: '/inventory/batches', icon: Layers, module: 'inventory' },
    ],
  },
  {
    label: 'SALES',
    items: [
      { name: 'Invoices', href: '/sales', icon: FileText, module: 'sales' },
      { name: 'New Sale', href: '/sales/new', icon: Plus, module: 'sales' },
      { name: 'Quotes', href: '/quotes', icon: ClipboardList, module: 'quotes' },
      { name: 'Recurring', href: '/recurring', icon: RefreshCw, module: 'recurring' },
    ],
  },
  {
    label: 'PROCUREMENT',
    items: [
      { name: 'Purchase Orders', href: '/purchases', icon: Truck, module: 'purchases' },
      { name: 'Bills (AP)', href: '/bills', icon: Receipt, module: 'bills' },
      { name: 'Suppliers', href: '/suppliers', icon: Building2, module: 'suppliers' },
    ],
  },
  {
    label: 'CRM',
    items: [
      { name: 'Customers', href: '/customers', icon: Users, module: 'customers' },
      { name: 'Credits', href: '/credits', icon: CreditCard, module: 'customers' },
    ],
  },
  {
    label: 'ACCOUNTING',
    items: [
      { name: 'Chart of Accounts', href: '/accounting/coa', icon: BookOpen, module: 'accounting' },
      { name: 'Journal Entries', href: '/accounting/journal', icon: BookMarked, module: 'accounting' },
      { name: 'Fixed Assets', href: '/accounting/assets', icon: Landmark, module: 'accounting' },
      { name: 'Bank Reconciliation', href: '/accounting/reconciliation', icon: Scale, module: 'accounting' },
      { name: 'Balance Sheet', href: '/reports/balance-sheet', icon: Scale, module: 'accounting' },
    ],
  },
  {
    label: 'PAYROLL',
    items: [
      { name: 'Employees', href: '/payroll/employees', icon: UsersRound, module: 'payroll' },
      { name: 'Payroll Runs', href: '/payroll/runs', icon: Banknote, module: 'payroll' },
    ],
  },
  {
    label: 'CASH FLOW',
    items: [
      { name: 'Income & Expenses', href: '/expenses', icon: ArrowDownCircle, module: 'expenses' },
      { name: 'Budgets', href: '/budgets', icon: PieChart, module: 'budget' },
      { name: 'Reports', href: '/reports', icon: BarChart3, module: 'reports' },
    ],
  },
  {
    label: 'COMPLIANCE',
    items: [
      { name: 'Tax', href: '/tax', icon: Calculator, module: 'tax' },
      { name: 'Audit Log', href: '/audit-log', icon: Shield, module: 'audit_log', ownerOnly: true },
    ],
  },
  {
    label: 'ACCOUNT',
    items: [
      { name: 'Billing & Plans', href: '/billing', icon: CreditCard, ownerOnly: true },
    ],
  },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const { user, organisation, tokens, logout, memberRole, modulePermissions, planModules } = useAuthStore()
  const navigate = useNavigate()

  const isOwnerOrAdmin = !memberRole || memberRole === 'owner' || memberRole === 'admin' || user?.is_superuser

  // Returns true if the nav item should be visible.
  // Checks: ownerOnly → plan modules → sub-account RBAC permissions
  const canSeeItem = (mod?: ModuleKey, ownerOnly?: boolean) => {
    if (ownerOnly && !isOwnerOrAdmin) return false   // explicitly owner-only items
    if (!mod) return true                             // no module restriction (dashboard, settings)
    if (user?.is_superuser) return true              // superusers always see everything
    // Plan-level gate: if the active plan restricts modules, only show allowed ones
    if (planModules !== null && !planModules.includes(mod)) return false
    if (isOwnerOrAdmin) return true                   // owners/admins see all plan-allowed modules
    const level = modulePermissions?.[mod]
    return level === 'view' || level === 'write' || level === 'edit'
  }

  // Track which groups are collapsed. All start expanded.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

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

  return (
    <aside
      className={cn(
        'fixed inset-y-0 left-0 z-30 w-64 flex flex-col',
        'bg-surface-900 border-r border-surface-700',
        'transition-transform duration-300 ease-in-out',
        'lg:relative lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full',
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-surface-700 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-white overflow-hidden flex items-center justify-center flex-shrink-0">
              <img src="/audity-logo.png" alt="Audity" className="w-7 h-7 object-contain" />
            </div>
          <div>
            <p className="font-bold text-white text-sm leading-tight">Audity</p>
            <p className="text-xs text-slate-500 leading-tight">Business Suite</p>
          </div>
        </div>
        <button onClick={onClose} className="lg:hidden btn-ghost p-1">
          <X size={18} />
        </button>
      </div>

      {/* Org badge */}
      {organisation && (
        <div className="mx-3 mt-3 px-3 py-2 bg-brand-500/10 border border-brand-500/20 rounded-xl shrink-0">
          <p className="text-xs text-slate-400 truncate">{organisation.name}</p>
          <p className="text-xs font-mono text-brand-400">{organisation.currency}</p>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
        {navGroups.map((group, gi) => {
          const isCollapsed = group.label ? (collapsed[group.label] ?? false) : false
          const visibleItems = group.items.filter((item) => canSeeItem(item.module, item.ownerOnly))
          if (group.label && visibleItems.length === 0) return null

          return (
            <div key={gi}>
              {group.label && (
                <button
                  onClick={() => toggleGroup(group.label!)}
                  className="w-full flex items-center justify-between px-3 pt-4 pb-1 text-left group"
                >
                  <span className="text-[10px] font-semibold text-slate-600 uppercase tracking-widest group-hover:text-slate-500 transition-colors">
                    {group.label}
                  </span>
                  {isCollapsed
                    ? <ChevronRight size={12} className="text-slate-600 group-hover:text-slate-500 transition-colors" />
                    : <ChevronDown size={12} className="text-slate-600 group-hover:text-slate-500 transition-colors" />
                  }
                </button>
              )}
              {!isCollapsed && visibleItems.map((item) => (
                <NavLink
                  key={item.href}
                  to={item.href}
                  end={item.href === '/sales'}
                  className={({ isActive }) =>
                    isActive ? 'sidebar-item-active' : 'sidebar-item'
                  }
                >
                  <item.icon size={16} className="shrink-0" />
                  <span className="truncate">{item.name}</span>
                </NavLink>
              ))}
            </div>
          )
        })}

        {/* Owner-only analytics */}
        {isOwnerOrAdmin && canSeeItem('owner_analytics') && (
          <div>
            <div className="px-3 pt-4 pb-1">
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
        {/* Settings: always show for owners/admins; for sub-accounts show only if they have profile/security access (always) */}
        <NavLink
          to="/settings"
          className={({ isActive }) => isActive ? 'sidebar-item-active' : 'sidebar-item'}
        >
          <Shield size={16} className="shrink-0" />
          Settings
        </NavLink>

        <button
          onClick={() => navigate('/settings')}
          className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-surface-700/50 rounded-xl transition-colors"
        >
          <div className="w-8 h-8 bg-brand-500 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0">
            {user?.first_name?.[0]}{user?.last_name?.[0]}
          </div>
          <div className="min-w-0 text-left">
            <p className="text-sm font-medium text-white truncate">
              {user?.first_name} {user?.last_name}
            </p>
            <p className="text-xs text-slate-500 truncate">{user?.email}</p>
          </div>
        </button>

        <button onClick={handleLogout} className="sidebar-item w-full text-red-400 hover:text-red-300 hover:bg-red-500/10">
          <LogOut size={16} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
