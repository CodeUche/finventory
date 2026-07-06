/**
 * Offline cache warm — behavioural tests.
 *
 * The warm itself just issues GETs through the api client (caching is the
 * response interceptor's job, covered by offlineSync tests). What matters
 * here:
 *   • priority — the selling path starts first (invoices, products, stock)
 *   • permission gating — no requests for modules the user can't view
 *   • plan gating — no requests for modules the plan excludes
 *   • pagination — products/customers/invoices follow `next` to the end
 *   • abort — going offline mid-warm stops it, and the next trigger resumes
 *   • session gating — never runs for offline grace sessions / missing tokens
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

const { calls } = vi.hoisted(() => ({ calls: [] as string[] }))

vi.mock('@/services/api', () => {
  const hit = (name: string, data: unknown = { results: [], next: null }) =>
    vi.fn(async () => { calls.push(name); return { data } })
  return {
    salesApi: { invoices: hit('sales.invoices') },
    inventoryApi: {
      products: hit('inventory.products'),
      stock: hit('inventory.stock'),
      warehouses: hit('inventory.warehouses'),
      batches: hit('inventory.batches'),
      categories: hit('inventory.categories'),
    },
    customerApi: { list: hit('customers.list') },
    quoteApi: { list: hit('quotes.list') },
    creditApi: { list: hit('credits.list') },
    locationApi: { list: hit('locations.list') },
    recurringApi: { list: hit('recurring.list') },
    invoiceFolderApi: { list: hit('invoiceFolders.list') },
    purchaseApi: { list: hit('purchases.list') },
    billApi: { list: hit('bills.list'), folders: hit('bills.folders') },
    supplierApi: { list: hit('suppliers.list') },
    expenseApi: { list: hit('expenses.list'), categories: hit('expenses.categories'), groups: hit('expenses.groups') },
    budgetApi: { list: hit('budgets.list') },
    accountingApi: { accounts: hit('accounting.accounts'), journal: hit('accounting.journal'), assets: hit('accounting.assets') },
    payrollApi: { employees: hit('payroll.employees'), runs: hit('payroll.runs') },
    taxApi: { classes: hit('tax.classes'), configs: hit('tax.configs'), obligations: hit('tax.obligations'), vatTransactions: hit('tax.vat') },
    whtApi: { rates: hit('wht.rates'), transactions: hit('wht.transactions') },
    exciseApi: { list: hit('excise.list') },
    orgApi: { list: hit('org.list') },
    teamApi: { members: hit('team.members') },
  }
})

import { warmOfflineCache, __resetWarmStateForTests } from '@/lib/cacheWarm'
import { useAuthStore } from '@/store/authStore'
import { salesApi, inventoryApi, customerApi } from '@/services/api'

const ORG = '11111111-1111-4111-8111-111111111111'

function setSession(overrides: Partial<ReturnType<typeof useAuthStore.getState>> = {}) {
  useAuthStore.setState({
    user: { id: 'u1', email: 't@example.com', is_superuser: false } as any,
    tokens: { access: 'a.b.c', refresh: 'r' } as any,
    isAuthenticated: true,
    isOfflineSession: false,
    organisation: { id: ORG } as any,
    memberRole: 'owner',
    modulePermissions: {},
    planModules: null,
    ...overrides,
  } as any)
}

beforeEach(() => {
  calls.length = 0
  vi.clearAllMocks()
  __resetWarmStateForTests()
  useAuthStore.getState().clearSession()
})

describe('warmOfflineCache', () => {
  it('warms everything for an owner, selling path first', async () => {
    setSession()
    await warmOfflineCache(ORG)

    // The 3-lane pool consumes the plan strictly in order, so the first three
    // requests to START are the top of the selling path.
    expect(calls.slice(0, 3)).toEqual(['sales.invoices', 'inventory.products', 'inventory.stock'])
    // Everything reachable was warmed, including the tail of the plan
    expect(calls).toContain('customers.list')
    expect(calls).toContain('accounting.accounts')
    expect(calls).toContain('tax.vat')
    expect(calls).toContain('org.list')
    // Second call for the same org is a no-op (already warmed this session)
    const count = calls.length
    await warmOfflineCache(ORG)
    expect(calls.length).toBe(count)
  })

  it('fully paginates products, customers, and sales invoices', async () => {
    setSession()
    // 3 pages each for the paginated trio
    const paged = (name: string) => {
      let served = 0
      return vi.fn(async () => {
        calls.push(name)
        served++
        return { data: { results: [], next: served < 3 ? `?page=${served + 1}` : null } }
      })
    }
    ;(salesApi.invoices as any).mockImplementation(paged('sales.invoices'))
    ;(inventoryApi.products as any).mockImplementation(paged('inventory.products'))
    ;(customerApi.list as any).mockImplementation(paged('customers.list'))

    await warmOfflineCache(ORG)

    expect(calls.filter((c) => c === 'sales.invoices').length).toBe(3)
    expect(calls.filter((c) => c === 'inventory.products').length).toBe(3)
    expect(calls.filter((c) => c === 'customers.list').length).toBe(3)
    // Non-paginated endpoints fetched exactly once
    expect(calls.filter((c) => c === 'inventory.warehouses').length).toBe(1)
  })

  it('skips modules a sub-account has no permission for — no 403 spam', async () => {
    setSession({
      memberRole: 'staff',
      modulePermissions: { sales: 'write', customers: 'view' } as any,
    })
    await warmOfflineCache(ORG)

    // sales + customers + always-on basics only
    expect(calls).toContain('sales.invoices')
    expect(calls).toContain('customers.list')
    expect(calls).toContain('org.list')
    // inventory / payroll / accounting / tax never requested
    expect(calls).not.toContain('inventory.products')
    expect(calls).not.toContain('payroll.employees')
    expect(calls).not.toContain('accounting.accounts')
    expect(calls).not.toContain('tax.classes')
  })

  it('skips modules the plan excludes, even for owners', async () => {
    setSession({ planModules: ['sales', 'inventory', 'customers'] })
    await warmOfflineCache(ORG)

    expect(calls).toContain('sales.invoices')
    expect(calls).toContain('inventory.products')
    expect(calls).not.toContain('payroll.employees')
    expect(calls).not.toContain('accounting.accounts')
    expect(calls).not.toContain('expenses.list')
  })

  it('aborts when the device goes offline mid-warm, and resumes on the next trigger', async () => {
    setSession()
    // First task knocks the connection out
    ;(salesApi.invoices as any).mockImplementationOnce(async () => {
      calls.push('sales.invoices')
      window.dispatchEvent(new Event('offline'))
      return { data: { results: [], next: null } }
    })

    await warmOfflineCache(ORG)
    // Only the tasks already started before the abort ran; the long tail didn't
    expect(calls).not.toContain('org.list')
    expect(calls).not.toContain('tax.classes')

    // Aborted warm is not marked complete — the reconnect trigger resumes it
    const before = calls.length
    await warmOfflineCache(ORG)
    expect(calls.length).toBeGreaterThan(before)
    expect(calls).toContain('org.list')
  })

  it('never runs during an offline grace session or without tokens', async () => {
    setSession({ isOfflineSession: true, tokens: null })
    await warmOfflineCache(ORG)
    expect(calls.length).toBe(0)

    setSession({ tokens: null })
    await warmOfflineCache(ORG)
    expect(calls.length).toBe(0)
  })
})
