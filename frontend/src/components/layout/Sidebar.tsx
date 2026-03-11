import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Package, Boxes, Plus, Layers,
  Users, Receipt, BarChart3, LogOut, Zap, X, FileText, RefreshCw,
  CreditCard, Truck, Building2, Warehouse, Calculator, BookOpen,
  BookMarked, Landmark, UsersRound, Banknote, ArrowDownCircle,
  PieChart, Scale, Shield, ClipboardList, ChevronDown, ChevronRight,
} from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'
import { cn } from '@/lib/utils'

// ─── Navigation structure ─────────────────────────────────────────────────────
const navGroups = [
  {
    label: null,
    items: [{ name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard }],
  },
  {
    label: 'INVENTORY',
    items: [
      { name: 'Products', href: '/inventory/products', icon: Package },
      { name: 'Stock Levels', href: '/inventory/stock', icon: Boxes },
      { name: 'Warehouses', href: '/inventory/warehouses', icon: Warehouse },
      { name: 'Batches & Lots', href: '/inventory/batches', icon: Layers },
    ],
  },
  {
    label: 'SALES',
    items: [
      { name: 'Invoices', href: '/sales', icon: FileText },
      { name: 'New Sale', href: '/sales/new', icon: Plus },
      { name: 'Quotes', href: '/quotes', icon: ClipboardList },
      { name: 'Recurring', href: '/recurring', icon: RefreshCw },
    ],
  },
  {
    label: 'PROCUREMENT',
    items: [
      { name: 'Purchase Orders', href: '/purchases', icon: Truck },
      { name: 'Bills (AP)', href: '/bills', icon: Receipt },
      { name: 'Suppliers', href: '/suppliers', icon: Building2 },
    ],
  },
  {
    label: 'CRM',
    items: [
      { name: 'Customers', href: '/customers', icon: Users },
      { name: 'Credits', href: '/credits', icon: CreditCard },
    ],
  },
  {
    label: 'ACCOUNTING',
    items: [
      { name: 'Chart of Accounts', href: '/accounting/coa', icon: BookOpen },
      { name: 'Journal Entries', href: '/accounting/journal', icon: BookMarked },
      { name: 'Fixed Assets', href: '/accounting/assets', icon: Landmark },
      { name: 'Bank Reconciliation', href: '/accounting/reconciliation', icon: Scale },
    ],
  },
  {
    label: 'PAYROLL',
    items: [
      { name: 'Employees', href: '/payroll/employees', icon: UsersRound },
      { name: 'Payroll Runs', href: '/payroll/runs', icon: Banknote },
    ],
  },
  {
    label: 'FINANCE',
    items: [
      { name: 'Income & Expenses', href: '/expenses', icon: ArrowDownCircle },
      { name: 'Budgets', href: '/budgets', icon: PieChart },
      { name: 'Reports', href: '/reports', icon: BarChart3 },
      { name: 'Balance Sheet', href: '/reports/balance-sheet', icon: Scale },
    ],
  },
  {
    label: 'COMPLIANCE',
    items: [
      { name: 'Tax', href: '/tax', icon: Calculator },
      { name: 'Audit Log', href: '/audit-log', icon: Shield },
    ],
  },
]

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const { user, organisation, tokens, logout } = useAuthStore()
  const navigate = useNavigate()

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
          <div className="w-9 h-9 bg-brand-500 rounded-xl flex items-center justify-center shadow-glow-orange">
            <Zap size={18} className="text-white" />
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
              {!isCollapsed && group.items.map((item) => (
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
