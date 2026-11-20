import React from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { trackPageview } from '@/lib/analytics'
import type { ModuleKey } from '@/types'
import AppLayout from '@/components/layout/AppLayout'
// Eager: first screens a user sees — keeping them in the entry chunk avoids a
// lazy-load spinner on login and immediately after it.
import LoginPage from '@/pages/auth/LoginPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'

// Lazy: everything else loads on first navigation. This splits the former
// ~4.9 MB single bundle into per-route chunks — critical for the cloud build
// on slow connections, harmless for the Tauri desktop build (local disk).
const SubAccountLoginPage = React.lazy(() => import('@/pages/auth/SubAccountLoginPage'))
import DsPage from '@/components/DsPage'
import RouteErrorBoundary from '@/components/RouteErrorBoundary'
const HubPage = React.lazy(() => import('@/pages/hubs/HubPage'))
const RegisterPage = React.lazy(() => import('@/pages/auth/RegisterPage'))
const OnboardingPage = React.lazy(() => import('@/pages/auth/OnboardingPage'))
const ForgotPasswordPage = React.lazy(() => import('@/pages/auth/ForgotPasswordPage'))
const VerifyEmailPage = React.lazy(() => import('@/pages/auth/VerifyEmailPage'))
const TermsPage = React.lazy(() => import('@/pages/legal/TermsPage'))
const PrivacyPage = React.lazy(() => import('@/pages/legal/PrivacyPage'))
const DpaPage = React.lazy(() => import('@/pages/legal/DpaPage'))
const ProductsPage = React.lazy(() => import('@/pages/inventory/ProductsPage'))
const StockPage = React.lazy(() => import('@/pages/inventory/StockPage'))
const WarehousesPage = React.lazy(() => import('@/pages/inventory/WarehousesPage'))
const BatchesPage = React.lazy(() => import('@/pages/inventory/BatchesPage'))
const SalesPage = React.lazy(() => import('@/pages/sales/SalesPage'))
const SalesReturnsPage = React.lazy(() => import('@/pages/sales/SalesReturnsPage'))
const NewSalePage = React.lazy(() => import('@/pages/sales/NewSalePage'))
const EditInvoicePage = React.lazy(() => import('@/pages/sales/EditInvoicePage'))
const ImportPage = React.lazy(() => import('@/pages/ImportPage'))
const QuotesPage = React.lazy(() => import('@/pages/QuotesPage'))
const RecurringInvoicesPage = React.lazy(() => import('@/pages/RecurringInvoicesPage'))
const CustomersPage = React.lazy(() => import('@/pages/customers/CustomersPage'))
const ExpensesPage = React.lazy(() => import('@/pages/expenses/ExpensesPage'))
const CreditsPage = React.lazy(() => import('@/pages/CreditsPage'))
const PurchasesPage = React.lazy(() => import('@/pages/PurchasesPage'))
const PurchaseReturnsPage = React.lazy(() => import('@/pages/PurchaseReturnsPage'))
const BillsPage = React.lazy(() => import('@/pages/BillsPage'))
const BillFoldersPage = React.lazy(() => import('@/pages/bills/BillFoldersPage'))
const SuppliersPage = React.lazy(() => import('@/pages/SuppliersPage'))
const ChartOfAccountsPage = React.lazy(() => import('@/pages/accounting/ChartOfAccountsPage'))
const JournalPage = React.lazy(() => import('@/pages/accounting/JournalPage'))
const GeneralLedgerPage = React.lazy(() => import('@/pages/accounting/GeneralLedgerPage'))
const AssetsPage = React.lazy(() => import('@/pages/accounting/AssetsPage'))
const DepreciationPage = React.lazy(() => import('@/pages/accounting/DepreciationPage'))
const BankReconciliationPage = React.lazy(() => import('@/pages/accounting/BankReconciliationPage'))
const GLHealthPage = React.lazy(() => import('@/pages/accounting/GLHealthPage'))
const BeginningBalancesPage = React.lazy(() => import('@/pages/accounting/BeginningBalancesPage'))
const EmployeesPage = React.lazy(() => import('@/pages/payroll/EmployeesPage'))
const PayrollPage = React.lazy(() => import('@/pages/payroll/PayrollPage'))
const LeavePage = React.lazy(() => import('@/pages/payroll/LeavePage'))
const CompliancePage = React.lazy(() => import('@/pages/payroll/CompliancePage'))
const OrgChartPage = React.lazy(() => import('@/pages/payroll/OrgChartPage'))
const HRAnalyticsPage = React.lazy(() => import('@/pages/payroll/HRAnalyticsPage'))
const EmployeePortalPage = React.lazy(() => import('@/pages/ess/EmployeePortalPage'))
const BudgetPage = React.lazy(() => import('@/pages/BudgetPage'))
const BudgetMonitoringPage = React.lazy(() => import('@/pages/BudgetMonitoringPage'))
const BudgetPeriodsPage = React.lazy(() => import('@/pages/BudgetPeriodsPage'))
const BudgetAllocationsPage = React.lazy(() => import('@/pages/BudgetAllocationsPage'))
const ReportsPage = React.lazy(() => import('@/pages/reports/ReportsPage'))
const BalanceSheetPage = React.lazy(() => import('@/pages/reports/BalanceSheetPage'))
const SalesByCustomerPage = React.lazy(() => import('@/pages/reports/SalesByCustomerPage'))
const SalesByProductPage = React.lazy(() => import('@/pages/reports/SalesByProductPage'))
const AllReportsPage = React.lazy(() => import('@/pages/reports/AllReportsPage'))
const OwnerAnalyticsPage = React.lazy(() => import('@/pages/dashboard/OwnerAnalyticsPage'))
const TaxPage = React.lazy(() => import('@/pages/TaxPage'))
const AuditLogPage = React.lazy(() => import('@/pages/AuditLogPage'))
const MessagesPage = React.lazy(() => import('@/pages/messaging/MessagesPage'))
const SettingsPage = React.lazy(() => import('@/pages/SettingsPage'))
const PlatformAdminPage = React.lazy(() => import('@/pages/PlatformAdminPage'))
const BillingPage = React.lazy(() => import('@/pages/BillingPage'))
// IntegrationsPage (raw webhooks + Zapier marketplace) is superseded by
// ConnectorsPage on the default nav — kept mounted, unlinked, so the one
// existing paying customer (McEva International) can still reach it via
// direct URL. See Sidebar.tsx: it is deliberately absent from navGroups.
const IntegrationsPage = React.lazy(() => import('@/pages/settings/IntegrationsPage'))
const ConnectorsPage = React.lazy(() => import('@/pages/settings/ConnectorsPage'))
const TicketsPage = React.lazy(() => import('@/pages/TicketsPage'))
const RestaurantPOSPage = React.lazy(() => import('@/pages/pos/RestaurantPOSPage'))
const TransferConfirmationsPage = React.lazy(() => import('@/pages/payments/TransferConfirmationsPage'))
const TillSessionPage = React.lazy(() => import('@/pages/pos/TillSessionPage'))
const PosRegisterPage = React.lazy(() => import('@/pages/pos/PosRegisterPage'))
const StorefrontPage = React.lazy(() => import('@/pages/shop/StorefrontPage'))
const OrderTrackingPage = React.lazy(() => import('@/pages/shop/OrderTrackingPage'))
const StorefrontAdminPage = React.lazy(() => import('@/pages/shop/StorefrontAdminPage'))
const SettlementPage = React.lazy(() => import('@/pages/payments/SettlementPage'))
const TablesPage = React.lazy(() => import('@/pages/pos/TablesPage'))
const KitchenPage = React.lazy(() => import('@/pages/pos/KitchenPage'))
const LocationsPage = React.lazy(() => import('@/pages/LocationsPage'))
const StockReportsPage = React.lazy(() => import('@/pages/inventory/StockReportsPage'))
const PartnerDashboardPage = React.lazy(() => import('@/pages/PartnerDashboardPage'))
const PartnerReportPage = React.lazy(() => import('@/pages/PartnerReportPage'))
const PartnerInvoicesPage = React.lazy(() => import('@/pages/PartnerInvoicesPage'))
const AcceptInvitePage = React.lazy(() => import('@/pages/auth/AcceptInvitePage'))

// Full-screen fallback while a lazy route chunk downloads
function RouteLoading() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-950">
      <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

// Last-resort boundary around the whole app (full screen). A second one sits
// around the page area inside AppLayout so the sidebar and top bar stay visible.
function ErrorBoundary({ children }: { children: React.ReactNode }) {
  return <RouteErrorBoundary fullScreen>{children}</RouteErrorBoundary>
}

/**
 * Where a signed-in user lands.
 *
 * Employee memberships hold no module permissions, so sending them to the
 * dashboard would show an empty shell; they belong in the self-service portal.
 */
function HomeRedirect() {
  const memberRole = useAuthStore((s) => s.memberRole)
  if (memberRole === 'employee') return <Navigate to="/me" replace />
  return <Navigate to="/dashboard" replace />
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, user, organisation, organisations, orgInitialized } = useAuthStore()
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

  // A user is only sent to /onboarding when they have NO organisation at all.
  // `organisations.length > 0` (persisted list) proves onboarding was already
  // completed — even if the ACTIVE organisation is momentarily null (e.g. a
  // transient re-auth or a mid-session store race), never bounce an existing
  // user back into the signup/onboarding flow; AppLayout re-selects the org.
  const onboardingDone =
    user?.is_superuser || user?.is_sub_account || !!organisation?.id || organisations.length > 0
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

// Plain names for the "no access" note.
const MODULE_NAMES: Partial<Record<ModuleKey, string>> = {
  sales: 'Sales', purchases: 'Purchases', bills: 'Bills', expenses: 'Income & Expenses',
  inventory: 'Inventory', customers: 'Customers', suppliers: 'Suppliers', payroll: 'HR and Payroll',
  reports: 'Reports', accounting: 'Accounting', tax: 'Tax', budget: 'Budgets', quotes: 'Quotes',
  recurring: 'Recurring Invoices', settings: 'Settings', audit_log: 'the Audit Log',
  owner_analytics: 'Owner Analytics', team: 'Team',
}

/**
 * Sends the person to the dashboard AND tells them why, once, in plain words,
 * instead of a silent redirect that looks like a bug.
 */
function DeniedRedirect({ what }: { what: string }) {
  React.useEffect(() => {
    toast(`You don't have access to ${what}. Ask an owner or admin.`, { id: 'no-access' })
  }, [what])
  return <Navigate to="/dashboard" replace />
}

/** Only owners, admins and superusers; anyone else goes to the dashboard with a note. */
function AdminOnlyRoute({ what, children }: { what: string; children: React.ReactNode }) {
  const { user, memberRole } = useAuthStore()
  if (!user) return <Navigate to="/login" replace />
  if (memberRole === null && !user.is_superuser) return <MembershipLoading />
  if (!isConfirmedOwnerOrAdmin(user, memberRole)) return <DeniedRedirect what={what} />
  return <>{children}</>
}

/** Small "Page not found" screen inside the app shell (sidebar and top bar stay). */
function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-6">
      <div role="alert" className="w-full max-w-md text-center" style={{ background: 'var(--ds-card)', border: '1.5px solid var(--ds-card-bd)', borderRadius: 16, padding: 32, color: 'var(--ds-ink)' }}>
        <h1 style={{ color: 'var(--ds-title)', fontSize: 22, fontWeight: 700, marginBottom: 8 }}>Page not found</h1>
        <p style={{ fontSize: 14, marginBottom: 20 }}>We could not find that page. It may have moved, or the address may have a typo.</p>
        <button type="button" className="btn-primary" onClick={() => navigate('/dashboard')}>Go to dashboard</button>
      </div>
    </div>
  )
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
  if (level === 'none') return <DeniedRedirect what={MODULE_NAMES[module] ?? 'that page'} />
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
  if (level === 'none' || level === 'view') return <DeniedRedirect what={MODULE_NAMES[module] ?? 'that page'} />
  return <>{children}</>
}

// Fires a PostHog $pageview whenever the route changes (SPA navigation).
function RouteAnalytics() {
  const location = useLocation()
  React.useEffect(() => {
    trackPageview(location.pathname + location.search)
  }, [location.pathname, location.search])
  return null
}

export default function App() {
  return (
    <ErrorBoundary>
    <RouteAnalytics />
    <React.Suspense fallback={<RouteLoading />}>
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      {/* Public storefront — no login, no Audity chrome. These sit with the
          other unauthenticated routes so it is obvious a customer reaches them
          without a session, and they must never be wrapped in ProtectedRoute. */}
      <Route path="/s/:slug" element={<StorefrontPage />} />
      <Route path="/s/:slug/t/:table" element={<StorefrontPage />} />
      <Route path="/s/:slug/order/:reference" element={<OrderTrackingPage />} />

      <Route path="/legal/terms" element={<TermsPage />} />
      <Route path="/legal/privacy" element={<PrivacyPage />} />
      <Route path="/legal/dpa" element={<DpaPage />} />
      <Route path="/staff-login" element={<SubAccountLoginPage />} />
      <Route path="/accept-invite/:token" element={<AcceptInvitePage mode="accept" />} />
      <Route path="/reject-invite/:token" element={<AcceptInvitePage mode="reject" />} />

      {/* Employee self-service portal — its own shell, never the operator layout.
          An employee membership has no module permissions, so routing them into
          AppLayout would land them on an empty dashboard. */}
      <Route
        path="/me"
        element={
          <ProtectedRoute>
            <EmployeePortalPage />
          </ProtectedRoute>
        }
      />

      {/* Protected */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<HomeRedirect />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="hub/:slug" element={<HubPage />} />

        {/* Inventory */}
        <Route path="inventory/products"      element={<ModuleRoute module="inventory"><DsPage><ProductsPage /></DsPage></ModuleRoute>} />
        <Route path="inventory/stock"         element={<ModuleRoute module="inventory"><DsPage><StockPage /></DsPage></ModuleRoute>} />
        <Route path="inventory/warehouses"    element={<ModuleRoute module="inventory"><DsPage><WarehousesPage /></DsPage></ModuleRoute>} />
        <Route path="inventory/batches"       element={<ModuleRoute module="inventory"><DsPage><BatchesPage /></DsPage></ModuleRoute>} />
        {/* Legacy URL — redirect to new reports module path */}
        <Route path="inventory/stock-reports" element={<Navigate to="/reports/stock" replace />} />

        {/* Sales */}
        <Route path="sales"     element={<ModuleRoute module="sales"><DsPage><SalesPage /></DsPage></ModuleRoute>} />
        <Route path="sales/returns" element={<ModuleRoute module="sales"><DsPage><SalesReturnsPage /></DsPage></ModuleRoute>} />
        <Route path="sales/new" element={<WriteModuleRoute module="sales"><DsPage><NewSalePage /></DsPage></WriteModuleRoute>} />
        {/* The old New Invoice address now opens the merged New sale & invoice page. */}
        <Route path="sales/invoices/new" element={<Navigate to="/sales/new" replace />} />
        <Route path="sales/invoices/:id/edit" element={<WriteModuleRoute module="sales"><DsPage><EditInvoicePage /></DsPage></WriteModuleRoute>} />
        <Route path="locations" element={<ModuleRoute module="sales"><DsPage><LocationsPage /></DsPage></ModuleRoute>} />
        <Route path="quotes"    element={<ModuleRoute module="quotes"><DsPage><QuotesPage /></DsPage></ModuleRoute>} />
        <Route path="recurring" element={<ModuleRoute module="recurring"><DsPage><RecurringInvoicesPage /></DsPage></ModuleRoute>} />

        {/* Procurement */}
        <Route path="purchases"      element={<ModuleRoute module="purchases"><DsPage><PurchasesPage /></DsPage></ModuleRoute>} />
        <Route path="purchases/returns" element={<ModuleRoute module="purchases"><DsPage><PurchaseReturnsPage /></DsPage></ModuleRoute>} />
        <Route path="bills"          element={<ModuleRoute module="bills"><DsPage><BillsPage /></DsPage></ModuleRoute>} />
        <Route path="bills/folders"  element={<ModuleRoute module="bills"><DsPage><BillFoldersPage /></DsPage></ModuleRoute>} />
        <Route path="suppliers"      element={<ModuleRoute module="suppliers"><DsPage><SuppliersPage /></DsPage></ModuleRoute>} />

        {/* CRM */}
        <Route path="customers" element={<ModuleRoute module="customers"><DsPage><CustomersPage /></DsPage></ModuleRoute>} />
        <Route path="credits"   element={<ModuleRoute module="customers"><DsPage><CreditsPage /></DsPage></ModuleRoute>} />

        {/* Accounting */}
        {/* Register — inside the app layout so the side menu is there. The menu is the normal
            sidebar, so it only lists what this person may open. Selling needs write access. */}
        <Route path="pos/register" element={<WriteModuleRoute module="sales"><PosRegisterPage /></WriteModuleRoute>} />
        <Route path="pos/restaurant"  element={<ModuleRoute module="sales"><DsPage><RestaurantPOSPage /></DsPage></ModuleRoute>} />
        <Route path="pos/tables"      element={<ModuleRoute module="sales"><TablesPage /></ModuleRoute>} />
        <Route path="pos/kitchen"     element={<ModuleRoute module="sales"><KitchenPage /></ModuleRoute>} />
        <Route path="accounting/coa"             element={<ModuleRoute module="accounting"><DsPage><ChartOfAccountsPage /></DsPage></ModuleRoute>} />
        <Route path="accounting/chart-of-accounts" element={<Navigate to="/accounting/coa" replace />} />
        <Route path="accounting/beginning-balances" element={<ModuleRoute module="accounting"><DsPage><BeginningBalancesPage /></DsPage></ModuleRoute>} />
        <Route path="accounting/journal"          element={<ModuleRoute module="accounting"><DsPage><JournalPage /></DsPage></ModuleRoute>} />
        <Route path="accounting/general-ledger"   element={<ModuleRoute module="accounting"><GeneralLedgerPage /></ModuleRoute>} />
        <Route path="accounting/assets"           element={<ModuleRoute module="accounting"><DsPage><AssetsPage /></DsPage></ModuleRoute>} />
        <Route path="accounting/depreciation"     element={<ModuleRoute module="accounting"><DepreciationPage /></ModuleRoute>} />
        <Route path="accounting/reconciliation"   element={<ModuleRoute module="accounting"><DsPage><BankReconciliationPage /></DsPage></ModuleRoute>} />
        <Route path="accounting/gl-health"        element={<ModuleRoute module="accounting"><DsPage><GLHealthPage /></DsPage></ModuleRoute>} />

        {/* Payroll */}
        {/* HR — canonical /hr/* paths. The old /payroll/* URLs are kept as
            redirects so bookmarks and the shipped desktop build keep working. */}
        <Route path="hr/employees"   element={<ModuleRoute module="payroll"><DsPage><EmployeesPage /></DsPage></ModuleRoute>} />
        <Route path="hr/runs"        element={<ModuleRoute module="payroll"><DsPage><PayrollPage /></DsPage></ModuleRoute>} />
        <Route path="hr/org-chart"   element={<ModuleRoute module="payroll"><DsPage><OrgChartPage /></DsPage></ModuleRoute>} />
        <Route path="hr/leave"       element={<ModuleRoute module="payroll"><DsPage><LeavePage /></DsPage></ModuleRoute>} />
        <Route path="hr/analytics"   element={<ModuleRoute module="payroll"><HRAnalyticsPage /></ModuleRoute>} />
        <Route path="hr/compliance"  element={<ModuleRoute module="payroll"><CompliancePage /></ModuleRoute>} />
        <Route path="payroll/employees" element={<Navigate to="/hr/employees" replace />} />
        <Route path="payroll/runs"      element={<Navigate to="/hr/runs" replace />} />

        {/* Finance */}
        <Route path="expenses"              element={<ModuleRoute module="expenses"><ExpensesPage /></ModuleRoute>} />
        <Route path="budgets"               element={<ModuleRoute module="budget"><DsPage><BudgetPage /></DsPage></ModuleRoute>} />
        <Route path="budgets/monitoring"    element={<ModuleRoute module="budget"><BudgetMonitoringPage /></ModuleRoute>} />
        <Route path="budgets/periods"       element={<ModuleRoute module="budget"><DsPage><BudgetPeriodsPage /></DsPage></ModuleRoute>} />
        <Route path="budgets/allocations"   element={<ModuleRoute module="budget"><DsPage><BudgetAllocationsPage /></DsPage></ModuleRoute>} />
        <Route path="reports"                       element={<ModuleRoute module="reports"><ReportsPage /></ModuleRoute>} />
        <Route path="reports/balance-sheet"         element={<ModuleRoute module="accounting"><BalanceSheetPage /></ModuleRoute>} />
        <Route path="reports/stock"                 element={<ModuleRoute module="inventory"><StockReportsPage /></ModuleRoute>} />
        <Route path="reports/sales-by-customer"     element={<ModuleRoute module="reports"><SalesByCustomerPage /></ModuleRoute>} />
        <Route path="reports/sales-by-product"      element={<ModuleRoute module="reports"><SalesByProductPage /></ModuleRoute>} />
        <Route path="reports/all"                   element={<ModuleRoute module="reports"><AllReportsPage /></ModuleRoute>} />
        <Route path="owner-analytics"       element={<OwnerOnlyRoute><OwnerAnalyticsPage /></OwnerOnlyRoute>} />

        {/* Compliance */}
        <Route path="tax"       element={<ModuleRoute module="tax"><TaxPage /></ModuleRoute>} />
        <Route path="audit-log" element={<AdminOnlyRoute what="the Audit Log"><AuditLogPage /></AdminOnlyRoute>} />
        <Route path="helpdesk" element={<TicketsPage />} />
        <Route path="messages" element={<MessagesPage />} />
        <Route path="payments/transfers" element={<ModuleRoute module="sales"><DsPage><TransferConfirmationsPage /></DsPage></ModuleRoute>} />
        <Route path="payments/settlement" element={<ModuleRoute module="sales"><DsPage><SettlementPage /></DsPage></ModuleRoute>} />
        <Route path="pos/till" element={<ModuleRoute module="sales"><DsPage><TillSessionPage /></DsPage></ModuleRoute>} />
        <Route path="storefront" element={<ModuleRoute module="sales"><DsPage><StorefrontAdminPage /></DsPage></ModuleRoute>} />

        {/* Settings — always accessible for personal profile/security; org tabs filtered inside the page */}
        <Route path="settings" element={<SettingsPage />} />
        <Route path="billing"  element={<ModuleRoute module="settings"><BillingPage /></ModuleRoute>} />
        <Route path="connectors" element={<ModuleRoute module="settings"><ConnectorsPage /></ModuleRoute>} />
        {/* Unlisted (no Sidebar link) — route intentionally kept alive so
            McEva International, an existing paying webhooks/Zapier customer,
            can still reach it via a direct URL from support. */}
        <Route path="integrations" element={<ModuleRoute module="settings"><IntegrationsPage /></ModuleRoute>} />
        <Route path="import"   element={<WriteModuleRoute module="settings"><ImportPage /></WriteModuleRoute>} />
        <Route path="partner"           element={<PartnerRoute><DsPage><PartnerDashboardPage /></DsPage></PartnerRoute>} />
        <Route path="partner/report"    element={<PartnerRoute><PartnerReportPage /></PartnerRoute>} />
        <Route path="partner/invoices"  element={<PartnerRoute><DsPage><PartnerInvoicesPage /></DsPage></PartnerRoute>} />

        {/* Platform Admin — superuser only */}
        <Route path="platform-admin" element={<SuperuserRoute><PlatformAdminPage /></SuperuserRoute>} />

        {/* Catch-all: a small "Page not found" screen inside the app shell */}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
    </React.Suspense>
    </ErrorBoundary>
  )
}
