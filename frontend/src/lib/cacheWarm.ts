/**
 * Offline cache warm — proactively loads every CRUD entity collection the
 * user can read, so the app is fully usable offline even for screens the
 * user hasn't visited yet this session.
 *
 * Product requirement: traders in local markets have highly unstable
 * internet. Login is online, but everything after must work offline with
 * full CRUD, syncing when connectivity returns. Without this warm, only
 * pages the user happened to open while online would be available offline.
 *
 * How it works
 * ────────────
 * Every request goes through the normal `api` client, so the response
 * interceptor writes it into offlineCache (exact URL) AND seeds localStore
 * (per-entity records) automatically — nothing here touches the caches
 * directly. The fresh-cache gate makes re-warms cheap: anything fetched in
 * the last 5 minutes is served from IndexedDB without a network hit.
 *
 * Rules:
 *   • Priority order — the selling path first (invoices, products, stock,
 *     customers …), bookkeeping modules after.
 *   • Permission-aware — modules the user can't view (module permissions)
 *     or that the plan excludes are skipped entirely: no 403/402 spam.
 *   • Staggered — a 3-lane worker pool so the warm never competes with the
 *     user's own actions for bandwidth.
 *   • Full pagination for products, customers, and sales invoices (traders
 *     need complete catalogs offline); first page only for the rest.
 *   • Silent — failures are swallowed; no spinners, no toasts.
 *   • Aborts when the device goes offline mid-warm; an aborted warm is NOT
 *     marked complete, so the next trigger (reconnect) resumes it.
 */

import {
  salesApi, inventoryApi, customerApi, quoteApi, creditApi, locationApi,
  recurringApi, invoiceFolderApi, purchaseApi, billApi, supplierApi,
  expenseApi, budgetApi, accountingApi, payrollApi, taxApi, whtApi,
  exciseApi, orgApi, teamApi,
} from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type { ModuleKey } from '@/types'

const CONCURRENCY = 3
// Safety cap on pagination: 60 pages × 25/page = 1 500 records per entity.
const MAX_PAGES = 60

interface WarmSignal { aborted: boolean }

interface WarmTask {
  /** Module gate — null means "always needed" (org/team basics). */
  module: ModuleKey | null
  run: (signal: WarmSignal) => Promise<void>
}

// ── Permission / plan gating ─────────────────────────────────────────────────
// Mirrors useModuleAccess (owner/admin/superuser bypass module permissions)
// and the Sidebar's plan gate (planModules applies to everyone but superusers).
function canWarmModule(module: ModuleKey | null): boolean {
  const s = useAuthStore.getState()
  if (module === null) return true
  if (s.user?.is_superuser) return true
  if (s.planModules !== null && !s.planModules.includes(module)) return false
  if (s.memberRole === 'owner' || s.memberRole === 'admin') return true
  return (s.modulePermissions[module] ?? 'none') !== 'none'
}

// ── Pagination helper ────────────────────────────────────────────────────────
// First request carries NO page param — that's the exact URL module pages
// request on mount, so the offline cache key matches. Subsequent pages follow
// DRF's `next` link via ?page=N.
async function fetchAllPages(
  fetchPage: (params?: object) => Promise<{ data: unknown }>,
  signal: WarmSignal,
): Promise<void> {
  const first = await fetchPage()
  let next = (first.data as { next?: string | null } | null)?.next
  let page = 2
  while (next && page <= MAX_PAGES && !signal.aborted && navigator.onLine) {
    const resp = await fetchPage({ page })
    next = (resp.data as { next?: string | null } | null)?.next
    page++
  }
}

// ── Warm plan (priority order: the selling path first) ───────────────────────
function buildWarmPlan(): WarmTask[] {
  const one = (module: ModuleKey | null, call: () => Promise<unknown>): WarmTask =>
    ({ module, run: async () => { await call() } })
  const paged = (module: ModuleKey | null, call: (params?: object) => Promise<{ data: unknown }>): WarmTask =>
    ({ module, run: (signal) => fetchAllPages(call, signal) })

  return [
    // ── Selling path — what a trader needs at the stall ──
    paged('sales', (p) => salesApi.invoices(p)),
    paged('inventory', (p) => inventoryApi.products(p)),
    one('inventory', () => inventoryApi.stock()),
    one('inventory', () => inventoryApi.warehouses()),
    one('inventory', () => inventoryApi.batches()),
    one('inventory', () => inventoryApi.categories()),
    paged('customers', (p) => customerApi.list(p)),
    one('quotes', () => quoteApi.list()),
    one('sales', () => creditApi.list()),
    one('sales', () => locationApi.list()),
    // ── The rest — bookkeeping and administration ──
    one('recurring', () => recurringApi.list()),
    one('sales', () => invoiceFolderApi.list()),
    one('purchases', () => purchaseApi.list()),
    one('bills', () => billApi.list()),
    one('bills', () => billApi.folders()),
    one('suppliers', () => supplierApi.list()),
    one('expenses', () => expenseApi.list()),
    one('expenses', () => expenseApi.categories()),
    one('expenses', () => expenseApi.groups()),
    one('budget', () => budgetApi.list()),
    one('accounting', () => accountingApi.accounts()),
    one('accounting', () => accountingApi.journal()),
    one('accounting', () => accountingApi.assets()),
    one('payroll', () => payrollApi.employees()),
    one('payroll', () => payrollApi.runs()),
    one('tax', () => taxApi.classes()),
    one('tax', () => taxApi.configs()),
    one('tax', () => taxApi.obligations()),
    one('tax', () => taxApi.vatTransactions()),
    one('tax', () => whtApi.rates()),
    one('tax', () => whtApi.transactions()),
    one('tax', () => exciseApi.list()),
    one('team', () => teamApi.members()),
    one(null, () => orgApi.list()),
  ]
}

// ── Runner ───────────────────────────────────────────────────────────────────

let _warming = false
// Orgs fully warmed this app session — aborted warms are NOT recorded, so a
// reconnect re-triggers and resumes (fresh-cache gate skips completed URLs).
const _warmedOrgs = new Set<string>()

/** Test hook — resets module state between test cases. */
export function __resetWarmStateForTests(): void {
  _warming = false
  _warmedOrgs.clear()
}

export async function warmOfflineCache(orgId: string): Promise<void> {
  if (_warming || _warmedOrgs.has(orgId)) return
  if (!navigator.onLine) return
  const s = useAuthStore.getState()
  // Real-token sessions only: an offline grace session can't reach the
  // network, and warming through the cache adapter would be a no-op anyway.
  if (!s.tokens?.access || s.isOfflineSession) return

  _warming = true
  const signal: WarmSignal = { aborted: false }
  const onOffline = () => { signal.aborted = true }
  window.addEventListener('offline', onOffline)

  try {
    const queue = buildWarmPlan().filter((t) => canWarmModule(t.module))
    const worker = async () => {
      while (queue.length > 0 && !signal.aborted && navigator.onLine) {
        const task = queue.shift()!
        try {
          await task.run(signal)
        } catch { /* silent — a failed warm just means that screen loads on demand */ }
      }
    }
    await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()))
    if (!signal.aborted) _warmedOrgs.add(orgId)
  } finally {
    window.removeEventListener('offline', onOffline)
    _warming = false
  }
}
