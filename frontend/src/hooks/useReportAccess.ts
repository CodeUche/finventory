/**
 * useReportAccess - which report routes this person may call.
 *
 * Mirrors the server (apps/core/permissions.py user_can_run_report): every
 * report needs the tick for the module whose data it shows, the role that
 * module's screens need (accounting and tax: accountant or above) and, for
 * non-admins, the plan module. Cost-bearing reports (cost price, inventory
 * value) are owner/admin only. Pages use these flags to skip a request the
 * server would refuse, so nobody sees a red "access denied" toast.
 */
import { useAuthStore } from '@/store/authStore'
import { useModuleAccess } from '@/hooks/useModuleAccess'

const ACCOUNTANT_OR_ABOVE = ['owner', 'admin', 'manager', 'accountant']

export const NO_REPORT_ACCESS_NOTE = 'Some reports need extra permission. Ask an owner or admin.'

export function useReportAccess() {
  const { memberRole, user, planModules } = useAuthStore()
  const sales = useModuleAccess('sales')
  const customers = useModuleAccess('customers')
  const bills = useModuleAccess('bills')
  const expenses = useModuleAccess('expenses')
  const tax = useModuleAccess('tax')
  const accounting = useModuleAccess('accounting')
  const inventory = useModuleAccess('inventory')

  const isAdmin = user?.is_superuser === true || memberRole === 'owner' || memberRole === 'admin'
  const accountantUp = isAdmin || (memberRole !== null && ACCOUNTANT_OR_ABOVE.includes(memberRole))
  // Owners and admins skip plan gates on the server; everyone else needs the plan module.
  const planOk = (key: string) => isAdmin || planModules === null || planModules.includes(key)

  const arAging = sales.canView
  const apAging = bills.canView && planOk('bills')
  const vatSummary = tax.canView && accountantUp
  const expenseBreakdown = expenses.canView
  const customerBalance = customers.canView
  const customerDetails = customers.canView
  const productDetails = inventory.canView && isAdmin
  const inventoryValuation = inventory.canView && isAdmin
  const paymentsByCustomer = sales.canView
  const accountStatement = accounting.canView && accountantUp && planOk('accounting')
  const customerInvoices = sales.canView

  return {
    arAging, apAging, vatSummary, expenseBreakdown, customerBalance, customerDetails,
    productDetails, inventoryValuation, paymentsByCustomer, accountStatement, customerInvoices,
    isAdmin,
  }
}
