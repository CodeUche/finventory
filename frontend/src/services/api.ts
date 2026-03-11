/**
 * Axios API client with JWT auth + tenant header injection.
 *
 * Automatically:
 *   - Injects Bearer token from Zustand auth store
 *   - Injects X-Organisation-ID from Zustand org store
 *   - Handles 401 by refreshing the access token
 *   - Redirects to /login on refresh failure
 */

import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { offlineQueue } from '@/lib/offlineQueue'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

// ─── Tauri HTTP plugin ────────────────────────────────────────────────────────
// In the packaged desktop app, WebView2 blocks XHR/fetch to http://localhost
// even with the loopback exemption applied. The Tauri HTTP plugin routes all
// requests through Rust's reqwest, completely bypassing WebView2 restrictions.
//
// We start loading the plugin immediately (IIFE), then the request interceptor
// awaits _tauriReady before the first request fires — zero race conditions.
let _tauriFetch: typeof fetch | null = null
const _tauriReady: Promise<void> =
  typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
    ? import('@tauri-apps/plugin-http')
        .then((m) => { _tauriFetch = m.fetch as typeof fetch })
        .catch(() => { /* fall back to native fetch */ })
    : Promise.resolve()

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
  adapter: 'fetch',
})

// ─── Storage helpers (sessionStorage-first for "no remember me") ──────────────
function getStoredAuth() {
  return JSON.parse(sessionStorage.getItem('auth') || localStorage.getItem('auth') || '{}')
}
function getStoredOrgId() {
  return sessionStorage.getItem('org_id') || localStorage.getItem('org_id')
}

// ─── Request interceptor ──────────────────────────────────────────────────────
api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  // Ensure Tauri plugin is loaded before the first request goes out
  await _tauriReady
  // Pass the Tauri fetch fn directly to Axios's fetch adapter (config.fetch takes priority)
  if (_tauriFetch) (config as any).fetch = _tauriFetch

  const auth = getStoredAuth()
  const orgId = getStoredOrgId()

  if (auth.access) {
    config.headers.Authorization = `Bearer ${auth.access}`
  }
  if (orgId) {
    config.headers['X-Organisation-ID'] = orgId
  }
  // FormData must NOT have Content-Type set — the browser adds the correct
  // multipart/form-data boundary automatically. Remove the global JSON default.
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }

  // ── Offline queue: if device is offline and this is a mutation, queue it ──
  const isRetry = (config.headers as Record<string, string>)?.['X-Offline-Retry'] === '1'
  const isMutation = ['post', 'put', 'patch', 'delete'].includes(config.method?.toLowerCase() ?? '')
  if (!navigator.onLine && isMutation && !isRetry) {
    offlineQueue.enqueue({ method: config.method!, url: config.url!, data: config.data })
    toast('Request queued — will sync when back online', { icon: '📋', id: 'queue-notice', duration: 3000 })
    // Reject with a network-style error so the component catch block fires
    return Promise.reject(new AxiosError('Offline — request queued', 'ERR_NETWORK', config))
  }

  return config
})

// ─── Response interceptor ─────────────────────────────────────────────────────
let isRefreshing = false
let failedQueue: Array<{ resolve: (v: unknown) => void; reject: (r: unknown) => void }> = []

const processQueue = (error: AxiosError | null, token: string | null = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else resolve(token)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !original._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          original.headers.Authorization = `Bearer ${token}`
          return api(original)
        })
      }

      original._retry = true
      isRefreshing = true

      const auth = getStoredAuth()
      if (!auth.refresh) {
        // No refresh token — clear state and let ProtectedRoute redirect (no full page reload)
        useAuthStore.getState().logout()
        return Promise.reject(error)
      }

      try {
        const { data } = await axios.post(`${API_BASE}/auth/token/refresh/`, { refresh: auth.refresh })
        // IMPORTANT: ROTATE_REFRESH_TOKENS=True means Django returns a NEW refresh token.
        // We must save it — otherwise the next refresh attempt uses a blacklisted token → logout.
        const newAuth = {
          ...auth,
          access: data.access,
          refresh: data.refresh ?? auth.refresh,  // save rotated refresh token
        }
        // Write back to whichever storage has the tokens
        if (sessionStorage.getItem('auth')) sessionStorage.setItem('auth', JSON.stringify(newAuth))
        else localStorage.setItem('auth', JSON.stringify(newAuth))
        // Also keep Zustand store in sync so inactivity logout uses the current refresh token
        useAuthStore.getState().updateTokens({ access: newAuth.access, refresh: newAuth.refresh })
        api.defaults.headers.common.Authorization = `Bearer ${data.access}`
        processQueue(null, data.access)
        original.headers.Authorization = `Bearer ${data.access}`
        return api(original)
      } catch (refreshError) {
        processQueue(refreshError as AxiosError, null)
        // Call logout() to clear all tokens — ProtectedRoute will redirect to /login smoothly
        useAuthStore.getState().logout()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // Show toast for API errors
    const errData = (error.response?.data as any)?.error
    if (errData?.message && error.response?.status !== 401) {
      toast.error(errData.message)
    }

    return Promise.reject(error)
  },
)

// ─── Typed helpers ────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login/', { email, password }),
  register: (data: object) => api.post('/auth/register/', data),
  logout: (refresh: string) => api.post('/auth/logout/', { refresh }),
  profile: () => api.get('/auth/profile/'),
  updateProfile: (data: FormData | object) => api.patch('/auth/profile/', data),
}

export const orgApi = {
  list: () => api.get('/tenancy/organisations/'),
  create: (data: object) => api.post('/tenancy/organisations/', data),
  update: (id: string, data: FormData | object) => api.patch(`/tenancy/organisations/${id}/`, data),
  getEmailConfig: (id: string) => api.get(`/tenancy/organisations/${id}/email_config/`),
  saveEmailConfig: (id: string, data: object) => api.patch(`/tenancy/organisations/${id}/email_config/`, data),
  myMembership: (orgId: string) => api.get(`/tenancy/organisations/${orgId}/my_membership/`),
  invite: (orgId: string, data: object) => api.post(`/tenancy/organisations/${orgId}/invite/`, data),
  createSubaccount: (orgId: string, data: object) => api.post(`/tenancy/organisations/${orgId}/create_subaccount/`, data),
  resolveBankAccount: (accountNumber: string, bankCode: string) =>
    api.get('/tenancy/organisations/resolve_bank_account/', { params: { account_number: accountNumber, bank_code: bankCode } }),
}

export const teamApi = {
  members: () => api.get('/tenancy/memberships/'),
  updateMember: (id: string, data: object) => api.patch(`/tenancy/memberships/${id}/`, data),
  setPermissions: (id: string, permissions: { module: string; access_level: string }[]) =>
    api.post(`/tenancy/memberships/${id}/set_permissions/`, { permissions }),
}

export const inventoryApi = {
  products: (params?: object) => api.get('/inventory/products/', { params }),
  product: (id: string) => api.get(`/inventory/products/${id}/`),
  createProduct: (data: object) => api.post('/inventory/products/', data),
  updateProduct: (id: string, data: object) => api.patch(`/inventory/products/${id}/`, data),
  stock: (params?: object) => api.get('/inventory/stock/', { params }),
  lowStock: () => api.get('/inventory/products/low-stock/'),
  valuation: () => api.get('/inventory/products/valuation/'),
  movements: (params?: object) => api.get('/inventory/movements/', { params }),
  warehouses: () => api.get('/inventory/warehouses/'),
  createWarehouse: (data: object) => api.post('/inventory/warehouses/', data),
  updateWarehouse: (id: string, data: object) => api.patch(`/inventory/warehouses/${id}/`, data),
  deleteWarehouse: (id: string) => api.delete(`/inventory/warehouses/${id}/`),
  adjustStock: (data: object) => api.post('/inventory/movements/adjust/', data),
  batches: (params?: object) => api.get('/inventory/batches/', { params }),
  createBatch: (data: object) => api.post('/inventory/batches/', data),
}

export const salesApi = {
  invoices: (params?: object) => api.get('/sales/invoices/', { params }),
  invoice: (id: string) => api.get(`/sales/invoices/${id}/`),
  create: (data: object) => api.post('/sales/invoices/', data),
  pay: (id: string, data: object) => api.post(`/sales/invoices/${id}/pay/`, data),
  void: (id: string) => api.post(`/sales/invoices/${id}/void/`),
  processReturn: (invoiceId: string, data: object) =>
    api.post(`/sales/invoices/${invoiceId}/process_return/`, data),
  listReturns: (params?: object) => api.get('/sales/returns/', { params }),
  sendEmail: (invoiceId: string, data: object) =>
    api.post(`/sales/invoices/${invoiceId}/send_email/`, data),
  confirmProforma: (invoiceId: string) =>
    api.post(`/sales/invoices/${invoiceId}/confirm_proforma/`),
  productHistory: (productId: string) =>
    api.get('/sales/invoices/product_history/', { params: { product_id: productId } }),
}

export const customerApi = {
  list: (params?: object) => api.get('/customers/', { params }),
  get: (id: string) => api.get(`/customers/${id}/`),
  create: (data: object) => api.post('/customers/', data),
  update: (id: string, data: object) => api.patch(`/customers/${id}/`, data),
  delete: (id: string) => api.delete(`/customers/${id}/`),
  statement: (id: string, params?: object) => api.get(`/customers/${id}/statement/`, { params }),
}

export const expenseApi = {
  list: (params?: object) => api.get('/expenses/', { params }),
  create: (data: object) => api.post('/expenses/', data),
  update: (id: string, data: object) => api.patch(`/expenses/${id}/`, data),
  categories: () => api.get('/expenses/categories/'),
  // Folders / groups
  groups: (params?: object) => api.get('/expenses/groups/', { params }),
  createGroup: (data: object) => api.post('/expenses/groups/', data),
  updateGroup: (id: string, data: object) => api.patch(`/expenses/groups/${id}/`, data),
  deleteGroup: (id: string) => api.delete(`/expenses/groups/${id}/`),
  groupContents: (id: string) => api.get(`/expenses/groups/${id}/contents/`),
}

export const creditApi = {
  list: (params?: object) => api.get('/credits/', { params }),
  recordPayment: (data: object) => api.post('/credits/record_payment/', data),
  agingReport: () => api.get('/credits/aging_report/'),
}

export const purchaseApi = {
  list: (params?: object) => api.get('/purchases/orders/', { params }),
  create: (data: object) => api.post('/purchases/orders/', data),
  patch: (id: string, data: FormData | object) => api.patch(`/purchases/orders/${id}/`, data),
}

export const supplierApi = {
  list: (params?: object) => api.get('/suppliers/', { params }),
  create: (data: object) => api.post('/suppliers/', data),
  update: (id: string, data: object) => api.patch(`/suppliers/${id}/`, data),
  delete: (id: string) => api.delete(`/suppliers/${id}/`),
}

export const reportApi = {
  pnl: (params: object) => api.get('/reports/pnl/', { params }),
  sales: (params: object) => api.get('/reports/sales/', { params }),
  topProducts: (params: object) => api.get('/reports/top-products/', { params }),
  topCustomers: (params: object) => api.get('/reports/top-customers/', { params }),
  inventory: () => api.get('/reports/inventory/'),
  cashFlow: (params: object) => api.get('/reports/cash-flow/', { params }),
  expenses: (params: object) => api.get('/reports/expenses/', { params }),
  arAging: (params?: object) => api.get('/reports/ar-aging/', { params }),
  vatSummary: (params: object) => api.get('/reports/vat-summary/', { params }),
}

export const taxApi = {
  // VAT Classes
  classes: () => api.get('/tax/classes/'),
  createClass: (data: object) => api.post('/tax/classes/', data),
  updateClass: (id: string, data: object) => api.patch(`/tax/classes/${id}/`, data),
  deleteClass: (id: string) => api.delete(`/tax/classes/${id}/`),
  // Tax Configs (income/corporate)
  configs: () => api.get('/tax/configs/'),
  createConfig: (data: object) => api.post('/tax/configs/', data),
  updateConfig: (id: string, data: object) => api.patch(`/tax/configs/${id}/`, data),
  deleteConfig: (id: string) => api.delete(`/tax/configs/${id}/`),
  setBrackets: (configId: string, brackets: object[]) =>
    api.put(`/tax/configs/${configId}/brackets/`, brackets),
  calculateIncomeTax: (data: object) => api.post('/tax/configs/calculate_income_tax/', data),
  vatReport: (data: object) => api.post('/tax/configs/vat_report/', data),
}

export const quoteApi = {
  list: (params?: object) => api.get('/quotes/', { params }),
  create: (data: object) => api.post('/quotes/', data),
  update: (id: string, data: object) => api.patch(`/quotes/${id}/`, data),
  send: (id: string) => api.post(`/quotes/${id}/send/`),
  accept: (id: string) => api.post(`/quotes/${id}/accept/`),
  reject: (id: string) => api.post(`/quotes/${id}/reject/`),
  convert: (id: string) => api.post(`/quotes/${id}/convert/`),
}

export const billApi = {
  list: (params?: object) => api.get('/bills/', { params }),
  create: (data: object) => api.post('/bills/', data),
  update: (id: string, data: object) => api.patch(`/bills/${id}/`, data),
  approve: (id: string) => api.post(`/bills/${id}/approve/`),
  pay: (id: string, data: object) => api.post(`/bills/${id}/pay/`, data),
  void: (id: string) => api.post(`/bills/${id}/void/`),
  folders: (params?: object) => api.get('/bills/folders/', { params }),
  createFolder: (data: object) => api.post('/bills/folders/', data),
  updateFolder: (id: string, data: object) => api.patch(`/bills/folders/${id}/`, data),
  deleteFolder: (id: string) => api.delete(`/bills/folders/${id}/`),
  folderContents: (id: string) => api.get(`/bills/folders/${id}/contents/`),
}

export const invoiceFolderApi = {
  list: (params?: object) => api.get('/sales/folders/', { params }),
  create: (data: object) => api.post('/sales/folders/', data),
  update: (id: string, data: object) => api.patch(`/sales/folders/${id}/`, data),
  delete: (id: string) => api.delete(`/sales/folders/${id}/`),
  contents: (id: string) => api.get(`/sales/folders/${id}/contents/`),
}

export const accountingApi = {
  accounts: (params?: object) => api.get('/accounting/accounts/', { params }),
  createAccount: (data: object) => api.post('/accounting/accounts/', data),
  updateAccount: (id: string, data: object) => api.patch(`/accounting/accounts/${id}/`, data),
  deleteAccount: (id: string) => api.delete(`/accounting/accounts/${id}/`),
  trialBalance: () => api.get('/accounting/accounts/trial_balance/'),
  balanceSheet: (params?: object) => api.get('/accounting/accounts/balance_sheet/', { params }),
  seedCoa: () => api.post('/accounting/accounts/seed/'),
  journal: (params?: object) => api.get('/accounting/journal/', { params }),
  createJournalEntry: (data: object) => api.post('/accounting/journal/', data),
  postJournalEntry: (id: string) => api.post(`/accounting/journal/${id}/post_entry/`),
  assets: () => api.get('/accounting/assets/'),
  createAsset: (data: object) => api.post('/accounting/assets/', data),
  updateAsset: (id: string, data: object) => api.patch(`/accounting/assets/${id}/`, data),
  runDepreciation: (data: object) => api.post('/accounting/assets/run_depreciation/', data),
  // Financial Periods
  periods: () => api.get('/accounting/periods/'),
  createPeriod: (data: object) => api.post('/accounting/periods/', data),
  lockPeriod: (id: string) => api.post(`/accounting/periods/${id}/lock/`),
  unlockPeriod: (id: string) => api.post(`/accounting/periods/${id}/unlock/`),
  // Bank Reconciliation
  reconciliations: () => api.get('/accounting/reconciliations/'),
  createReconciliation: (data: object) => api.post('/accounting/reconciliations/', data),
  markReconciled: (id: string) => api.post(`/accounting/reconciliations/${id}/mark_reconciled/`),
  addReconLine: (id: string, data: object) => api.post(`/accounting/reconciliations/${id}/add_line/`, data),
  updateReconLine: (id: string, data: object) => api.patch(`/accounting/reconciliations/${id}/update_line/`, data),
}

export const payrollApi = {
  employees: (params?: object) => api.get('/payroll/employees/', { params }),
  createEmployee: (data: object) => api.post('/payroll/employees/', data),
  updateEmployee: (id: string, data: object) => api.patch(`/payroll/employees/${id}/`, data),
  runs: () => api.get('/payroll/runs/'),
  runPayroll: (data: object) => api.post('/payroll/runs/', data),
  approvePayroll: (id: string) => api.post(`/payroll/runs/${id}/approve/`),
  markPaid: (id: string, data: object) => api.post(`/payroll/runs/${id}/mark_paid/`, data),
  initiateTransfers: (id: string) => api.post(`/payroll/runs/${id}/initiate_transfers/`),
  resolveAccount: (account_number: string, bank_code: string) =>
    api.post('/payroll/employees/resolve_account/', { account_number, bank_code }),
}

export const budgetApi = {
  list: () => api.get('/budgets/'),
  create: (data: object) => api.post('/budgets/', data),
  update: (id: string, data: object) => api.patch(`/budgets/${id}/`, data),
  variance: (id: string) => api.get(`/budgets/${id}/variance/`),
  addLine: (id: string, data: object) => api.post(`/budgets/${id}/add_line/`, data),
}

export const recurringApi = {
  list: () => api.get('/sales/recurring/'),
  create: (data: object) => api.post('/sales/recurring/', data),
  update: (id: string, data: object) => api.patch(`/sales/recurring/${id}/`, data),
  delete: (id: string) => api.delete(`/sales/recurring/${id}/`),
  generateNow: (id: string) => api.post(`/sales/recurring/${id}/generate_now/`),
}

export const paymentGatewayApi = {
  configs: () => api.get('/payments/gateways/'),
  createConfig: (data: object) => api.post('/payments/gateways/', data),
  updateConfig: (id: string, data: object) => api.patch(`/payments/gateways/${id}/`, data),
  createLink: (invoiceId: string) => api.post('/payments/links/create_link/', { invoice_id: invoiceId }),
  links: (params?: object) => api.get('/payments/links/', { params }),
}

export const exciseApi = {
  list: () => api.get('/tax/excise/'),
  create: (data: object) => api.post('/tax/excise/', data),
  update: (id: string, data: object) => api.patch(`/tax/excise/${id}/`, data),
  delete: (id: string) => api.delete(`/tax/excise/${id}/`),
}

export const whtApi = {
  rates: () => api.get('/tax/wht-rates/'),
  createRate: (data: object) => api.post('/tax/wht-rates/', data),
  updateRate: (id: string, data: object) => api.patch(`/tax/wht-rates/${id}/`, data),
  deleteRate: (id: string) => api.delete(`/tax/wht-rates/${id}/`),
  transactions: (params?: object) => api.get('/tax/wht-transactions/', { params }),
}

export const auditLogApi = {
  list: (params?: object) => api.get('/audit-log/', { params }),
}

export const platformAdminApi = {
  stats: () => api.get('/platform/stats/'),
  users: () => api.get('/platform/users/'),
}
