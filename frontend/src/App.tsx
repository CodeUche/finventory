import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import AppLayout from '@/components/layout/AppLayout'
import LoginPage from '@/pages/auth/LoginPage'
import RegisterPage from '@/pages/auth/RegisterPage'
import OnboardingPage from '@/pages/auth/OnboardingPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import ProductsPage from '@/pages/inventory/ProductsPage'
import StockPage from '@/pages/inventory/StockPage'
import WarehousesPage from '@/pages/inventory/WarehousesPage'
import BatchesPage from '@/pages/inventory/BatchesPage'
import SalesPage from '@/pages/sales/SalesPage'
import NewSalePage from '@/pages/sales/NewSalePage'
import QuotesPage from '@/pages/QuotesPage'
import RecurringInvoicesPage from '@/pages/RecurringInvoicesPage'
import CustomersPage from '@/pages/customers/CustomersPage'
import ExpensesPage from '@/pages/expenses/ExpensesPage'
import CreditsPage from '@/pages/CreditsPage'
import PurchasesPage from '@/pages/PurchasesPage'
import BillsPage from '@/pages/BillsPage'
import SuppliersPage from '@/pages/SuppliersPage'
import ChartOfAccountsPage from '@/pages/accounting/ChartOfAccountsPage'
import JournalPage from '@/pages/accounting/JournalPage'
import AssetsPage from '@/pages/accounting/AssetsPage'
import EmployeesPage from '@/pages/payroll/EmployeesPage'
import PayrollPage from '@/pages/payroll/PayrollPage'
import BudgetPage from '@/pages/BudgetPage'
import ReportsPage from '@/pages/reports/ReportsPage'
import BalanceSheetPage from '@/pages/reports/BalanceSheetPage'
import TaxPage from '@/pages/TaxPage'
import AuditLogPage from '@/pages/AuditLogPage'
import SettingsPage from '@/pages/SettingsPage'
import PlatformAdminPage from '@/pages/PlatformAdminPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

function SuperuserRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/login" replace />
  if (!user.is_superuser) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />

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
        <Route path="inventory/products" element={<ProductsPage />} />
        <Route path="inventory/stock" element={<StockPage />} />
        <Route path="inventory/warehouses" element={<WarehousesPage />} />
        <Route path="inventory/batches" element={<BatchesPage />} />

        {/* Sales */}
        <Route path="sales" element={<SalesPage />} />
        <Route path="sales/new" element={<NewSalePage />} />
        <Route path="quotes" element={<QuotesPage />} />
        <Route path="recurring" element={<RecurringInvoicesPage />} />

        {/* Procurement */}
        <Route path="purchases" element={<PurchasesPage />} />
        <Route path="bills" element={<BillsPage />} />
        <Route path="suppliers" element={<SuppliersPage />} />

        {/* CRM */}
        <Route path="customers" element={<CustomersPage />} />
        <Route path="credits" element={<CreditsPage />} />

        {/* Accounting */}
        <Route path="accounting/coa" element={<ChartOfAccountsPage />} />
        <Route path="accounting/journal" element={<JournalPage />} />
        <Route path="accounting/assets" element={<AssetsPage />} />

        {/* Payroll */}
        <Route path="payroll/employees" element={<EmployeesPage />} />
        <Route path="payroll/runs" element={<PayrollPage />} />

        {/* Finance */}
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="budgets" element={<BudgetPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/balance-sheet" element={<BalanceSheetPage />} />

        {/* Compliance */}
        <Route path="tax" element={<TaxPage />} />
        <Route path="audit-log" element={<AuditLogPage />} />

        {/* Settings */}
        <Route path="settings" element={<SettingsPage />} />

        {/* Platform Admin — superuser only */}
        <Route path="platform-admin" element={<SuperuserRoute><PlatformAdminPage /></SuperuserRoute>} />
      </Route>
    </Routes>
  )
}
