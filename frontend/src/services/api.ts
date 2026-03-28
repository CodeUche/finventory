/**
 * Axios API client with JWT auth + tenant header injection.
 *
 * Automatically:
 *   - Injects Bearer token from Zustand auth store
 *   - Injects X-Organisation-ID from Zustand org store
 *   - Handles 401 by refreshing the access token
 *   - Redirects to /login on refresh failure
 */

import axios, { AxiosError, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { fetch as tauriHttpFetch } from '@tauri-apps/plugin-http'
import toast from 'react-hot-toast'
import { useAuthStore } from '@/store/authStore'
import { offlineQueue } from '@/lib/offlineQueue'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

// ─── Tauri HTTP adapter ───────────────────────────────────────────────────────
// Uses @tauri-apps/plugin-http's fetch() which routes through Rust reqwest via
// Tauri IPC, bypassing WebView2 CORS entirely.  Falls back to native fetch()
// in web-browser contexts (plugin throws when __TAURI_INTERNALS__ is absent).
//
// Static import (not dynamic) so Vite bundles it at compile time — no silent
// failures like the dynamic-import approach that caused the original 401 bug.

// Resolved immediately — kept so the interceptor can await it symmetrically.
const _tauriReady: Promise<void> = Promise.resolve()

// ── Shared response converter (Response → AxiosResponse) ──────────────────
async function responseToAxios(resp: Response, config: InternalAxiosRequestConfig): Promise<AxiosResponse> {
  const respHeaders: Record<string, string> = {}
  resp.headers.forEach((v, k) => { respHeaders[k.toLowerCase()] = v })
  const ct = respHeaders['content-type'] ?? ''
  let data: unknown
  if (ct.includes('application/json')) {
    try { data = await resp.json() } catch { data = await resp.text() }
  } else if (config.responseType === 'blob') {
    data = await resp.blob()
  } else if (config.responseType === 'arraybuffer') {
    data = await resp.arrayBuffer()
  } else {
    data = await resp.text()
  }
  const axiosResp: AxiosResponse = {
    data, status: resp.status, statusText: resp.statusText,
    headers: respHeaders as never, config,
  }
  if (resp.ok) return axiosResp
  throw new AxiosError(`Request failed with status code ${resp.status}`, 'ERR_BAD_RESPONSE', config, null, axiosResp)
}

function buildTauriAdapter(): AxiosAdapter {
  return async (config): Promise<AxiosResponse> => {
    const method = (config.method ?? 'GET').toUpperCase()

    // Build absolute URL + query string
    const base = (config.baseURL ?? '').replace(/\/+$/, '')
    const path = (config.url ?? '').replace(/^\/+/, '')
    let url = path.startsWith('http') ? path : `${base}/${path}`
    if (config.params) {
      const qs = Object.entries(config.params as Record<string, unknown>)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
      if (qs) url += (url.includes('?') ? '&' : '?') + qs
    }

    // Extract headers via toJSON(true) — most reliable way to flatten an
    // AxiosHeaders instance to a plain { key: string } object.
    // toJSON(true) joins multi-value headers with ', ' and skips null/false entries.
    const rawHeaders = (config.headers?.toJSON?.(true) ?? config.headers ?? {}) as Record<string, unknown>
    const headers: Record<string, string> = {}
    for (const [k, v] of Object.entries(rawHeaders)) {
      if (typeof v === 'string' && v) headers[k] = v
    }
    console.debug('[Audity] adapter headers:', JSON.stringify(Object.keys(headers)))

    const body = !['GET', 'HEAD'].includes(method) && config.data != null
      ? (config.data instanceof FormData ? config.data : config.data as string)
      : undefined

    // Try Tauri IPC fetch first (routes through Rust reqwest, no CORS).
    // Only catch IPC-level errors (plugin not available / scope mismatch).
    // AxiosErrors thrown by responseToAxios for non-2xx MUST propagate directly —
    // they are real HTTP errors, not IPC failures.
    let ipcResponse: Response | null = null
    try {
      ipcResponse = await tauriHttpFetch(url, { method, headers, body } as RequestInit)
    } catch (ipcErr) {
      // IPC unavailable or URL not in scope — fall back to native browser fetch.
      console.error('[Audity] tauriHttpFetch threw:', String(ipcErr))
      toast.error(`[Audity] IPC error: ${String(ipcErr).slice(0, 100)}`, { id: 'ipc-err', duration: 15000 })
      const resp = await fetch(url, { method, headers, body } as RequestInit)
      return responseToAxios(resp, config)
    }
    // IPC succeeded — convert and return (throws AxiosError for non-2xx, propagates up)
    return responseToAxios(ipcResponse, config)
  }
}

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
  // Always use the Tauri adapter. It detects __TAURI_INTERNALS__ at request
  // time (not module init) to avoid a race in tauri dev where the IPC object
  // is injected after modules are evaluated. Falls back to native fetch in
  // pure web browser contexts.
  adapter: buildTauriAdapter(),
})

// ─── Storage helpers ──────────────────────────────────────────────────────────
// Read directly from Zustand in-memory state — always reflects the latest
// setAuth() call instantly, with no localStorage serialisation/timing gap.
function getStoredAuth(): { access?: string; refresh?: string } {
  return useAuthStore.getState().tokens ?? {}
}
function getStoredOrgId(): string | null {
  return useAuthStore.getState().organisation?.id ?? null
}

// ─── Request interceptor ──────────────────────────────────────────────────────
api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  await _tauriReady  // no-op (resolved immediately) — kept for symmetry

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

    // Never attempt a token refresh for auth endpoints — a 401 there is a real credential
    // failure, not an expired token. Bypassing these prevents isRefreshing from getting stuck.
    const isAuthEndpoint = original.url?.includes('/auth/login/') ||
                           original.url?.includes('/auth/token/')

    if (error.response?.status === 401 && !original._retry && !isAuthEndpoint) {
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
        // No refresh token — reset flag, drain queue, clear state
        isRefreshing = false
        processQueue(error, null)
        useAuthStore.getState().logout()
        return Promise.reject(error)
      }

      try {
        const { data } = await api.post('/auth/token/refresh/', { refresh: auth.refresh })
        // IMPORTANT: ROTATE_REFRESH_TOKENS=True means Django returns a NEW refresh token.
        // We must save it — otherwise the next refresh attempt uses a blacklisted token → logout.
        const newAuth = {
          ...auth,
          access: data.access,
          refresh: data.refresh ?? auth.refresh,  // save rotated refresh token
        }
        // Write rotated tokens back into Zustand persisted state
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

    // 402 — plan limit reached: show upgrade prompt
    if (error.response?.status === 402) {
      const errMsg = (error.response.data as any)?.error
      const msg = typeof errMsg === 'string' ? errMsg : 'Plan limit reached.'
      toast.error(`${msg} Upgrade your plan to continue.`, {
        id: 'plan-limit',
        duration: 6000,
        icon: '⚡',
      })
      return Promise.reject(error)
    }

    // Show toast for API errors (deduplicate using toast ID so poll loops don't spam)
    const errData = (error.response?.data as any)?.error
    if (errData?.message && error.response?.status !== 401) {
      const toastId = `api-err-${error.response?.status}-${original.url}`
      toast.error(errData.message, { id: toastId, duration: 4000 })
    }

    return Promise.reject(error)
  },
)

// ─── Tauri-aware media fetch ──────────────────────────────────────────────────
// Use this instead of native fetch() to load images/files in the Tauri desktop
// app — native fetch() to http://localhost is blocked by WebView2.
export async function tauriFetch(url: string): Promise<Response> {
  try {
    return await tauriHttpFetch(url)
  } catch {
    return fetch(url)
  }
}

// ─── Binary file upload (bypasses Tauri FormData/multipart bug) ───────────────
// Tauri's IPC layer serialises FormData as application/x-www-form-urlencoded
// instead of multipart/form-data. This helper sends the file as raw binary with
// an explicit Content-Type so the Django backend receives it correctly.
export async function uploadFileDirect(
  urlPath: string,   // e.g. '/tenancy/organisations/abc/upload_logo/'
  file: File,
): Promise<Response> {
  const base = API_BASE.startsWith('http')
    ? API_BASE.replace(/\/$/, '')
    : 'http://localhost:8000/api/v1'
  const { access } = getStoredAuth()
  const orgId = getStoredOrgId()
  const ab = await file.arrayBuffer()
  try {
    return await tauriHttpFetch(`${base}${urlPath}`, {
      method: 'POST',
      headers: {
        ...(access ? { Authorization: `Bearer ${access}` } : {}),
        ...(orgId ? { 'X-Organisation-ID': orgId } : {}),
        'Content-Type': file.type || 'application/octet-stream',
      },
      body: ab,
    } as RequestInit)
  } catch {
    return fetch(`${base}${urlPath}`, {
      method: 'POST',
      headers: {
        ...(access ? { Authorization: `Bearer ${access}` } : {}),
        ...(orgId ? { 'X-Organisation-ID': orgId } : {}),
        'Content-Type': file.type || 'application/octet-stream',
      },
      body: ab,
    })
  }
}

// ─── Typed helpers ────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login/', { email, password }),
  register: (data: object) => api.post('/auth/register/', data),
  logout: (refresh: string) => api.post('/auth/logout/', { refresh }),
  profile: () => api.get('/auth/profile/'),
  updateProfile: (data: object) => api.patch('/auth/profile/', data),
  uploadAvatar: (file: File) => uploadFileDirect('/auth/upload_avatar/', file),
  requestPasswordReset: (email: string) =>
    api.post('/auth/password-reset/', { email }),
  confirmPasswordReset: (data: { email: string; code: string; new_password: string; confirm_password: string }) =>
    api.post('/auth/password-reset/confirm/', data),
  verifyEmail: (token: string) =>
    api.get('/auth/verify-email/', { params: { token } }),
  resendVerification: (email: string) =>
    api.post('/auth/resend-verification/', { email }),
  mfaSetup: () => api.post('/auth/mfa/setup/'),
  mfaConfirmSetup: (code: string) => api.post('/auth/mfa/confirm-setup/', { code }),
  mfaVerify: (mfa_token: string, code: string) => api.post('/auth/mfa/verify/', { mfa_token, code }),
  mfaDisable: (code: string) => api.post('/auth/mfa/disable/', { code }),
  staffLogin: (username: string, orgSlug: string, password: string) =>
    api.post('/auth/staff-login/', { username, org_slug: orgSlug, password }),
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
  removeLogo: (id: string) => api.post(`/tenancy/organisations/${id}/remove_logo/`),
  removeStamp: (id: string) => api.post(`/tenancy/organisations/${id}/remove_stamp/`),
  uploadLogo: (id: string, file: File) => uploadFileDirect(`/tenancy/organisations/${id}/upload_logo/`, file),
  uploadStamp: (id: string, file: File) => uploadFileDirect(`/tenancy/organisations/${id}/upload_stamp/`, file),
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
  updateInvoice: (id: string, data: object) => api.patch(`/sales/invoices/${id}/`, data),
  deleteInvoice: (id: string) => api.delete(`/sales/invoices/${id}/`),
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
  warehouseSales: (period?: string) =>
    api.get('/sales/invoices/warehouse_sales/', { params: { period } }),
  ownerAnalytics: (period?: string) =>
    api.get('/sales/invoices/owner_analytics/', { params: { period } }),
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
  delete: (id: string) => api.delete(`/expenses/${id}/`),
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
  delete: (id: string) => api.delete(`/purchases/orders/${id}/`),
  removeReceipt: (id: string) => api.post(`/purchases/orders/${id}/clear_receipt/`),
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
  apAging: (params?: object) => api.get('/reports/ap-aging/', { params }),
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
  sendEmail: (id: string, data: object) => api.post(`/quotes/${id}/send_email/`, data),
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
  importStatement: (id: string, file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return api.post(`/accounting/reconciliations/${id}/import_statement/`, fd)
  },
  aiReconcile: (id: string) => api.post(`/accounting/reconciliations/${id}/ai_reconcile/`),
  confirmMatch: (id: string, data: { match_id: string; action: 'confirm' | 'reject' }) =>
    api.post(`/accounting/reconciliations/${id}/confirm_match/`, data),
}

export const payrollApi = {
  employees: (params?: object) => api.get('/payroll/employees/', { params }),
  createEmployee: (data: object) => api.post('/payroll/employees/', data),
  updateEmployee: (id: string, data: object) => api.patch(`/payroll/employees/${id}/`, data),
  deleteEmployee: (id: string) => api.delete(`/payroll/employees/${id}/`),
  runs: () => api.get('/payroll/runs/'),
  runPayroll: (data: object) => api.post('/payroll/runs/', data),
  approvePayroll: (id: string) => api.post(`/payroll/runs/${id}/approve/`),
  markPaid: (id: string, data: object) => api.post(`/payroll/runs/${id}/mark_paid/`, data),
  initiateTransfers: (id: string) => api.post(`/payroll/runs/${id}/initiate_transfers/`),
  submitForApproval: (id: string) => api.post(`/payroll/runs/${id}/submit_for_approval/`),
  retryFailed: (id: string) => api.post(`/payroll/runs/${id}/retry_failed/`),
  exportBankFile: (id: string) => api.get(`/payroll/runs/${id}/export_bank_file/`, { responseType: 'blob' }),
  pendingApprovals: () => api.get('/payroll/runs/pending_approvals/'),
  resolveAccount: (account_number: string, bank_code: string) =>
    api.post('/payroll/employees/resolve_account/', { account_number, bank_code }),
  // Bonuses
  bonuses: (params?: object) => api.get('/payroll/bonuses/', { params }),
  createBonus: (data: object) => api.post('/payroll/bonuses/', data),
  deleteBonus: (id: string) => api.delete(`/payroll/bonuses/${id}/`),
  // Attendance
  attendance: (params?: object) => api.get('/payroll/attendance/', { params }),
  markAttendance: (data: object) => api.post('/payroll/attendance/', data),
  bulkMarkAttendance: (data: object) => api.post('/payroll/attendance/bulk_mark/', data),
  updateAttendance: (id: string, data: object) => api.patch(`/payroll/attendance/${id}/`, data),
  // Penalties
  penalties: (employeeId: string) =>
    api.get('/payroll/penalties/', { params: { employee: employeeId } }),
  createPenalty: (data: object) => api.post('/payroll/penalties/', data),
  waivePenalty: (id: string) => api.post(`/payroll/penalties/${id}/waive/`),
  deletePenalty: (id: string) => api.delete(`/payroll/penalties/${id}/`),
  // Loans
  loans: (employeeId: string) =>
    api.get('/payroll/loans/', { params: { employee: employeeId } }),
  createLoan: (data: object) => api.post('/payroll/loans/', data),
  cancelLoan: (id: string) => api.post(`/payroll/loans/${id}/cancel/`),
  // Employee documents
  documents: (employeeId: string) =>
    api.get('/payroll/documents/', { params: { employee: employeeId } }),
  uploadDocument: (data: FormData) => api.post('/payroll/documents/', data),
  deleteDocument: (id: string) => api.delete(`/payroll/documents/${id}/`),
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

export const subscriptionApi = {
  plans: () => api.get('/subscriptions/plans/'),
  current: () => api.get('/subscriptions/current/'),
  payments: () => api.get('/subscriptions/payments/'),
  initiatePayment: (planId: string) => api.post('/subscriptions/initiate-payment/', { plan_id: planId }),
  verifyPayment: (reference: string) => api.post('/subscriptions/verify-payment/', { reference }),
  cancel: () => api.post('/subscriptions/cancel/'),
  recommendPlan: (answers: Record<string, string>) => api.post('/subscriptions/recommend-plan/', { answers }),
  checkPayment: (reference: string) => api.get('/subscriptions/check-payment/', { params: { reference } }),
  startTrial: (planId: string) => api.post('/subscriptions/start-trial/', { plan_id: planId }),
}

export const aiApi = {
  status: () => api.get('/ai/status/'),
  chat: (message: string) => api.post('/ai/chat/', { message }),
}
