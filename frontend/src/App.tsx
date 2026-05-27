import React from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import type { ModuleKey } from '@/types'
import AppLayout from '@/components/layout/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import SubAccountLoginPage from '@/pages/auth/SubAccountLoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import OnboardingPage from '@/pages/auth/OnboardingPage'
import ForgotPasswordPage from '@/pages/auth/ForgotPasswordPage'
import VerifyEmailPage from '@/pages/auth/VerifyEmailPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import ProductsPage from '@/pages/inventory/ProductsPage'
import StockPage from '@/pages/inventory/StockPage'
import WarehousesPage from '@/pages/inventory/WarehousesPage'
import BatchesPage from '@/pages/inventory/BatchesPage'
import SalesPage from '@/pages/sales/SalesPage'
import NewSalePage from '@/pages/sales/NewSalePage'
import EditInvoicePage from '@/pages/sales/EditInvoicePage'
import ImportPage from '@/pages/ImportPage'
import QuotesPage from '@/pages/QuotesPage'
import RecurringInvoicesPage from '@/pages/RecurringInvoicesPage'
import CustomersPage from '@/pages/customers/CustomersPage'
import ExpensesPage from '@/pages/expenses/ExpensesPage'
import CreditsPage from '@/pages/CreditsPage'
import PurchasesPage from '@/pages/PurchasesPage'
import BillsPage from '@/pages/BillsPage'
import BillFoldersPage from '@/pages/bills/BillFoldersPage'
import SuppliersPage from '@/pages/SuppliersPage'
import ChartOfAccountsPage from '@/pages/accounting/ChartOfAccountsPage'
import JournalPage from '@/pages/accounting/JournalPage'
import AssetsPage from '@/pages/accounting/AssetsPage'
import BankReconciliationPage from '@/pages/accounting/BankReconciliationPage'
import EmployeesPage from '@/pages/payroll/EmployeesPage'
import PayrollPage from '@/pages/payroll/PayrollPage'
import BudgetPage from '@/pages/BudgetPage'
import ReportsPage from '@/pages/reports/ReportsPage'
import BalanceSheetPage from '@/pages/reports/BalanceSheetPage'
import SalesByCustomerPage from '@/pages/reports/SalesByCustomerPage'
import SalesByProductPage from '@/pages/reports/SalesByProductPage'
import OwnerAnalyticsPage from '@/pages/dashboard/OwnerAnalyticsPage'
import TaxPage from '@/pages/TaxPage'
import AuditLogPage from '@/pages/AuditLogPage'
import SettingsPage from '@/pages/SettingsPage'
import PlatformAdminPage from '@/pages/PlatformAdminPage'
import BillingPage from '@/pages/BillingPage'
import LocationsPage from '@/pages/LocationsPage'
import StockReportsPage from '@/pages/inventory/StockReportsPage'
import PartnerDashboardPage from '@/pages/PartnerDashboardPage'
import PartnerReportPage from '@/pages/PartnerReportPage'
import PartnerInvoicesPage from '@/pages/PartnerInvoicesPage'
import AcceptInvitePage from '@/pages/auth/AcceptInvitePage'

// Inner class-based boundary — must be a class to use getDerivedStateFromError
class ErrorBoundaryInner extends React.Component<
  { children: React.ReactNode; resetKey: string; navigate: (path: string) => void },
  { hasError: boolean; message: string }
> {
  constructor(props: { children: React.ReactNode; resetKey: string; navigate: (path: string) => void }) {
    super(props)
    this.state = { hasError: false, message: '' }
  }
  static getDerivedStateFromError(err: Error) {
    return { hasError: true, message: err?.message ?? 'Unknown error' }
  }
  componentDidUpdate(prev: { resetKey: string }) {
    // Reset error state whenever the route changes so a stale crash doesn't
    // keep the error screen visible on subsequent navigations
    if (prev.resetKey !== this.props.resetKey && this.state.hasError) {
      this.setState({ hasError: false, message: '' })
    }
  }
  render() {
    if (this.state.hasError) {
      // Use inline styles so the error card is always visible regardless of theme
      return (
        <div style={{ minHeight: '100vh', background: '#020617', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '16px', padding: '32px', maxWidth: '400px', width: '100%', textAlign: 'center' }}>
            <p style={{ color: '#f8fafc', fontSize: '18px', fontWeight: 700, marginBottom: '8px' }}>Something went wrong</p>
            <p style={{ color: '#94a3b8', fontSize: '12px', fontFamily: 'monospace', wordBreak: 'break-all', marginBottom: '20px' }}>{this.state.message}</p>
            <button
              style={{ background: '#f97316', color: '#fff', border: 'none', borderRadius: '8px', padding: '10px 24px', cursor: 'pointer', fontWeight: 600, fontSize: '14px' }}
              onClick={() => {
                this.setState({ hasError: false, message: '' })
                // Use React Router navigate so Tauri never does a full-page reload
                // (window.location.replace('/') triggers main.tsx logout() on restart)
                this.props.navigate('/dashboard')
              }}
            >
              Go to Dashboard
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

// Wrapper that supplies the current route path and navigate fn as props.
// navigate is passed explicitly because class components cannot use hooks.
function ErrorBoundary({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  return <ErrorBoundaryInner resetKey={location.pathname} navigate={navigate}>{children}</ErrorBoundaryInner>
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, user, organisation, orgInitialized } = useAuthStore()
  if (!isAuthenticated) return <Navigate to="/login" replace />

  // orgInitialized is only set to true by initSession() after finishLogin() has
  // fetched the org list and committed everything atomically.  While it is false
  // the login is still in-flight — show a full-screen spinner so we never redirect
  // to /onboarding based on the transient null organisation that exists between
  // setAuth() and setOrganisation() in older non-atomic code paths.
  if (!orgInitialized) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-950">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  const onboardingDone = user?.is_superuser || user?.is_sub_account || !!organisation?.id
  if (!onboardingDone) return <Navigate to="/onboarding" replace />
  return <>{children}</>
}

function SuperuserRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (!user.is_superuser) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

function PartnerRoute({ children }: { children: React.ReactNode }) {
  const { user, memberRole } = useAuthStore()
  if (!user) return <Navigate to="/login" replace />
  if (memberRole === null && !user.is_superuser) return <MembershipLoading />
  if (user.is_superuser) return <>{children}</>
  if (!user.has_partner_profile) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

// Shared loading placeholder shown while membership is being fetched
function MembershipLoading() {
  return (
    <div className="flex-1 flex items-center justify-center py-20">
      <div className="w-6 h-6 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// Returns true if this user is confirmed owner/admin (not null — null means still loading)
function isConfirmedOwnerOrAdmin(user: any, memberRole: string | null) {
  return user?.is_superuser === true || memberRole === 'owner' || memberRole === 'admin'
}

/** Allows owners, admins, and superusers; redirects regular sub-accounts and Starter plan users. */
function OwnerOnlyRoute({ children }: { children: React.ReactNode }) {
  const { user, memberRole, planModules } = useAuthStore()
  if (!user) return <Navigate to="/login" replace />
  // Wait for membership to load before deciding
  if (memberRole === null && !user.is_superuser) return <MembershipLoading />
  if (!isConfirmedOwnerOrAdmin(user, memberRole)) return <Navigate to="/dashboard" replace />
  // Starter plan has no 'owner_analytics' module — redirect to billing
  if (planModules !== null && !planModules.includes('owner_analytics') && !user.is_superuser)
    return <Navigate to="/billing" replace />
  return <>{children}</>
}

/**
 * Redirects sub-accounts to /dashboard if they have 'none' access on a module.
 * Owners, admins, and superusers always pass through.
 */
function ModuleRoute({ module, children }: { module: ModuleKey; children: React.ReactNode }) {
  const { user, memberRole, modulePermissions } = useAuthStore()
  if (isConfirmedOwnerOrAdmin(user, memberRole)) return <>{children}</>
  // Wait for membership to load — show spinner instead of redirecting prematurely
  if (memberRole === null) return <MembershipLoading />
  const level = modulePermissions[module] ?? 'none'
  if (level === 'none') return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

/**
 * Like ModuleRoute but also blocks 'view'-only users (who cannot write).
 * Used for create/new-record pages.
 */
function WriteModuleRoute({ module, children }: { module: ModuleKey; children: React.ReactNode }) {
  const { user, memberRole, modulePermissions } = useAuthStore()
  if (isConfirmedOwnerOrAdmin(user, memberRole)) return <>{children}</>
  if (memberRole === null) return <MembershipLoading />
  const level = modulePermissions[module] ?? 'none'
  if (level === 'none' || level === 'view') return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <ErrorBoundary>
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/staff-login" element={<SubAccountLoginPage />} />
      <Route path="/accept-invite/:token" element={<AcceptInvitePage mode="accept" />} />
      <Route path="/reject-invite/:token" element={<AcceptInvitePage mode="reject" />} />

      {/* Protected */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />

        {/* Inventory */}
        <Route path="inventory/products"      element={<ModuleRoute module="inventory"><ProductsPage /></ModuleRoute>} />
        <Route path="inventory/stock"         element={<ModuleRoute module="inventory"><StockPage /></ModuleRoute>} />
        <Route path="inventory/warehouses"    element={<ModuleRoute module="inventory"><WarehousesPage /></ModuleRoute>} />
        <Route path="inventory/batches"       element={<ModuleRoute module="inventory"><BatchesPage /></ModuleRoute>} />
        {/* Legacy URL — redirect to new reports module path */}
        <Route path="inventory/stock-reports" element={<Navigate to="/reports/stock" replace />} />

        {/* Sales */}
        <Route path="sales"     element={<ModuleRoute module="sales"><SalesPage /></ModuleRoute>} />
        <Route path="sales/new" element={<WriteModuleRoute module="sales"><NewSalePage /></WriteModuleRoute>} />
        <Route path="sales/invoices/:id/edit" element={<WriteModuleRoute module="sales"><EditInvoicePage /></WriteModuleRoute>} />
        <Route path="locations" element={<ModuleRoute module="sales"><LocationsPage /></ModuleRoute>} />
        <Route path="quotes"    element={<ModuleRoute module="quotes"><QuotesPage /></ModuleRoute>} />
        <Route path="recurring" element={<ModuleRoute module="recurring"><RecurringInvoicesPage /></ModuleRoute>} />

        {/* Procurement */}
        <Route path="purchases"      element={<ModuleRoute module="purchases"><PurchasesPage /></ModuleRoute>} />
        <Route path="bills"          element={<ModuleRoute module="bills"><BillsPage /></ModuleRoute>} />
        <Route path="bills/folders"  element={<ModuleRoute module="bills"><BillFoldersPage /></ModuleRoute>} />
        <Route path="suppliers"      element={<ModuleRoute module="suppliers"><SuppliersPage /></ModuleRoute>} />

        {/* CRM */}
        <Route path="customers" element={<ModuleRoute module="customers"><CustomersPage /></ModuleRoute>} />
        <Route path="credits"   element={<ModuleRoute module="customers"><CreditsPage /></ModuleRoute>} />

        {/* Accounting */}
        <Route path="accounting/coa"             element={<ModuleRoute module="accounting"><ChartOfAccountsPage /></ModuleRoute>} />
        <Route path="accounting/journal"          element={<ModuleRoute module="accounting"><JournalPage /></ModuleRoute>} />
        <Route path="accounting/assets"           element={<ModuleRoute module="accounting"><AssetsPage /></ModuleRoute>} />
        <Route path="accounting/reconciliation"   element={<ModuleRoute module="accounting"><BankReconciliationPage /></ModuleRoute>} />

        {/* Payroll */}
        <Route path="payroll/employees" element={<ModuleRoute module="payroll"><EmployeesPage /></ModuleRoute>} />
        <Route path="payroll/runs"      element={<ModuleRoute module="payroll"><PayrollPage /></ModuleRoute>} />

        {/* Finance */}
        <Route path="expenses"              element={<ModuleRoute module="expenses"><ExpensesPage /></ModuleRoute>} />
        <Route path="budgets"               element={<ModuleRoute module="budget"><BudgetPage /></ModuleRoute>} />
        <Route path="reports"                       element={<ModuleRoute module="reports"><ReportsPage /></ModuleRoute>} />
        <Route path="reports/balance-sheet"         element={<ModuleRoute module="accounting"><BalanceSheetPage /></ModuleRoute>} />
        <Route path="reports/stock"                 element={<ModuleRoute module="inventory"><StockReportsPage /></ModuleRoute>} />
        <Route path="reports/sales-by-customer"     element={<ModuleRoute module="reports"><SalesByCustomerPage /></ModuleRoute>} />
        <Route path="reports/sales-by-product"      element={<ModuleRoute module="reports"><SalesByProductPage /></ModuleRoute>} />
        <Route path="owner-analytics"       element={<OwnerOnlyRoute><OwnerAnalyticsPage /></OwnerOnlyRoute>} />

        {/* Compliance */}
        <Route path="tax"       element={<ModuleRoute module="tax"><TaxPage /></ModuleRoute>} />
        <Route path="audit-log" element={<AuditLogPage />} />

        {/* Settings — always accessible for personal profile/security; org tabs filtered inside the page */}
        <Route path="settings" element={<SettingsPage />} />
        <Route path="billing"  element={<ModuleRoute module="settings"><BillingPage /></ModuleRoute>} />
        <Route path="import"   element={<WriteModuleRoute module="settings"><ImportPage /></WriteModuleRoute>} />
        <Route path="partner"           element={<PartnerRoute><PartnerDashboardPage /></PartnerRoute>} />
        <Route path="partner/report"    element={<PartnerRoute><PartnerReportPage /></PartnerRoute>} />
        <Route path="partner/invoices"  element={<PartnerRoute><PartnerInvoicesPage /></PartnerRoute>} />

        {/* Platform Admin — superuser only */}
        <Route path="platform-admin" element={<SuperuserRoute><PlatformAdminPage /></SuperuserRoute>} />

        {/* Catch-all: redirect unknown paths to dashboard */}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
    </ErrorBoundary>
  )
}
