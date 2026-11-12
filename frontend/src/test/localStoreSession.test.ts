/**
 * Saved data and sign-out/sign-in timing:
 *  - a background warm-up that is still running at sign-out must not leave
 *    data on disk, now or later;
 *  - nothing is saved when nobody is signed in or no business is selected;
 *  - saved data is scoped to the user, so another user can never read it even
 *    if a wipe did not happen;
 *  - identity endpoints are never saved or served from saved copies.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { stores, apiCalls } = vi.hoisted(() => ({
  stores: new Map<string, Map<string, any>>(),
  apiCalls: { n: 0 },
}))

vi.mock('idb', () => ({
  openDB: vi.fn(async (name: string) => {
    if (!stores.has(name)) stores.set(name, new Map())
    const store = stores.get(name)!
    const keyOf = (v: any) => v._key ?? v.id ?? v.key
    return {
      close: () => {},
      getAll: async () => [...store.values()],
      getAllFromIndex: async (_s: string, _i: string, [o, t]: [string, string]) =>
        [...store.values()].filter((v) => v._orgId === o && v._entityType === t),
      get: async (_s: string, k: string) => store.get(k),
      put: async (_s: string, v: any) => { store.set(keyOf(v), v) },
      delete: async (_s: string, k: string) => { store.delete(k) },
      clear: async () => { store.clear() },
      transaction: () => ({
        store: { put: (v: any) => { store.set(keyOf(v), v) }, delete: (k: string) => { store.delete(k) } },
        done: Promise.resolve(),
      }),
      objectStoreNames: { contains: () => true },
    }
  }),
}))
vi.mock('@/lib/dialog', () => ({ alertDialog: vi.fn(async () => {}) }))
vi.mock('@/lib/analytics', () => ({ resetAnalytics: vi.fn(), identifyUser: vi.fn() }))

// Every API the warm-up calls: slow, and like the real response interceptor it
// writes its answer into the saved copies when it comes back (with NO session
// number, the worst case for the guard).
vi.mock('@/services/api', async () => {
  const { offlineCache } = await import('@/lib/offlineCache')
  const { localStore } = await import('@/lib/localStore')
  const names = ['salesApi', 'inventoryApi', 'customerApi', 'quoteApi', 'creditApi', 'locationApi', 'recurringApi',
    'invoiceFolderApi', 'purchaseApi', 'billApi', 'supplierApi', 'expenseApi', 'budgetApi', 'accountingApi', 'payrollApi',
    'taxApi', 'whtApi', 'exciseApi', 'orgApi', 'teamApi']
  const slow = async () => {
    apiCalls.n++
    await new Promise((r) => setTimeout(r, 30))
    await offlineCache.set('/payroll/employees/', { results: [{ id: 'e1', name: 'Real Employee' }] })
    await localStore.upsertMany('org-1', 'employees', [{ id: 'e1', name: 'Real Employee' }])
    return { data: { next: null } }
  }
  const mod: Record<string, unknown> = {
    api: { defaults: { headers: { common: {} } } },
    authApi: { revokeOfflineVerifier: vi.fn(async () => ({ data: {} })) },
  }
  for (const n of names) mod[n] = new Proxy({}, { get: () => slow })
  return mod
})

import { localStore } from '@/lib/localStore'
import { offlineCache } from '@/lib/offlineCache'
import { warmOfflineCache, __resetWarmStateForTests } from '@/lib/cacheWarm'
import { retryPendingWipe } from '@/lib/localDataGuard'
import { useAuthStore } from '@/store/authStore'

const ORG = 'org-1'
const org = { id: ORG, name: 'O', slug: 'o', account_type: 'business', currency: 'NGN', country: 'NG' }
const signIn = (id: string) => useAuthStore.getState().initSession(
  { id, email: `${id}@example.com`, first_name: 'A', last_name: 'B', phone: '', is_verified: true } as any,
  { access: 'a.b.c', refresh: 'r' } as any, org as any, [org] as any,
)
const onDisk = () => (stores.get('audity-local-store')?.size ?? 0) + (stores.get('audity-offline-cache')?.size ?? 0)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

beforeEach(async () => {
  await retryPendingWipe()
  stores.forEach((m) => m.clear())
  localStorage.clear()
  useAuthStore.getState().clearSession()
  apiCalls.n = 0
  __resetWarmStateForTests()
})

describe('background warm-up and sign-out', () => {
  it('signing out right after the warm-up starts leaves nothing on disk, now or later', async () => {
    signIn('owner')
    useAuthStore.setState({ memberRole: 'owner', planModules: null })
    const warm = warmOfflineCache(ORG)
    useAuthStore.getState().logout() // +0 s
    await warm
    for (let i = 0; i < 5; i++) {
      await sleep(300)
      expect(onDisk()).toBe(0)
    }
    // and the warm-up stopped instead of working through its whole plan
    expect(apiCalls.n).toBeLessThan(10)
  })

  it('nothing is saved when nobody is signed in, even from a request that started earlier', async () => {
    signIn('owner')
    useAuthStore.getState().clearSession()
    await offlineCache.set('/payroll/employees/', { results: [{ id: 'x' }] })
    await localStore.upsert(ORG, 'employees', 'x', { id: 'x' })
    await localStore.upsertMany(ORG, 'employees', [{ id: 'y' }])
    expect(onDisk()).toBe(0)
  })

  it('nothing is saved under "anonymous" or when no business is selected', async () => {
    signIn('owner')
    await localStore.upsert('anonymous', 'accounts', 'a1', { id: 'a1' })
    await localStore.upsert('unknown', 'accounts', 'a2', { id: 'a2' })
    expect(onDisk()).toBe(0)
    useAuthStore.setState({ organisation: null })
    await offlineCache.set('/accounting/accounts/', { results: [] })
    expect(onDisk()).toBe(0)
  })
})

describe('another user can never read saved data, even if no wipe happened', () => {
  it('entries are scoped to the user', async () => {
    signIn('owner')
    await sleep(30) // let the first sign-in's wipe finish; writes are dropped while one is owed
    await offlineCache.set('/payroll/runs/', { results: [{ id: 'r1' }] })
    await localStore.upsert(ORG, 'runs', 'r1', { id: 'r1' })
    expect(await offlineCache.get('/payroll/runs/')).not.toBeNull()

    // Simulate a wipe that never happened: the marker already names the next user.
    useAuthStore.getState().clearSession()
    localStorage.setItem('audity:cache-owner-user-id', 'staff')
    signIn('staff')
    expect(onDisk()).toBe(2) // the owner's entries are still there ...
    expect(await offlineCache.get('/payroll/runs/')).toBeNull() // ... but unreadable to staff
    expect(await localStore.getAll(ORG, 'runs')).toEqual([])
    expect(await localStore.getOne(ORG, 'runs', 'r1')).toBeNull()

    // The owner, signing back in with the marker restored, still has theirs.
    useAuthStore.getState().clearSession()
    localStorage.setItem('audity:cache-owner-user-id', 'owner')
    signIn('owner')
    await sleep(30)
    expect(await offlineCache.get('/payroll/runs/')).not.toBeNull()
  })

  it('identity endpoints are never saved or served', async () => {
    signIn('owner')
    await offlineCache.set('/auth/profile/', { id: 'owner', first_name: 'Owner' })
    await offlineCache.set('/auth/me/', { id: 'owner' })
    expect(onDisk()).toBe(0)
    expect(await offlineCache.get('/auth/profile/')).toBeNull()
  })

  it('a profile answer for a different user cannot replace who is signed in', () => {
    signIn('owner')
    useAuthStore.getState().updateUser({ id: 'staff', first_name: 'Deborah' } as any)
    expect(useAuthStore.getState().user?.id).toBe('owner')
    useAuthStore.getState().updateUser({ id: 'owner', first_name: 'Ada' } as any)
    expect(useAuthStore.getState().user?.first_name).toBe('Ada')
  })
})

describe('warm-up after sign-out and sign-in in the same run', () => {
  it('runs again, because sign-out wiped the saved copy', async () => {
    signIn('owner')
    await sleep(30)
    useAuthStore.setState({ memberRole: 'owner', planModules: null })
    await warmOfflineCache(ORG)
    const first = apiCalls.n
    expect(first).toBeGreaterThan(0)
    await warmOfflineCache(ORG) // already done for this user and business: skipped
    expect(apiCalls.n).toBe(first)

    useAuthStore.getState().logout()
    await sleep(30)
    signIn('owner')
    await sleep(30)
    useAuthStore.setState({ memberRole: 'owner', planModules: null })
    await warmOfflineCache(ORG)
    expect(apiCalls.n).toBeGreaterThan(first)
  })
})

describe('slow answers for a person who is no longer signed in', () => {
  it('stillSignedInAs is true only for the current user', async () => {
    const { stillSignedInAs } = await import('@/lib/localDataGuard')
    signIn('owner')
    expect(stillSignedInAs('owner')).toBe(true)
    expect(stillSignedInAs('staff')).toBe(false)
    expect(stillSignedInAs(undefined)).toBe(false)
    useAuthStore.getState().logout()
    expect(stillSignedInAs('owner')).toBe(false)
  })
})

describe('one-time cleanup of entries saved before they were user-scoped', () => {
  const put = (db: string, key: string, value: Record<string, unknown>) => {
    if (!stores.has(db)) stores.set(db, new Map())
    stores.get(db)!.set(key, value)
  }
  const seedLegacy = () => {
    put('audity-offline-cache', 'org-1||/payroll/runs/', { key: 'org-1||/payroll/runs/', url: '/payroll/runs/', data: { results: [] }, cachedAt: 1 })
    put('audity-offline-cache', 'anonymous||/tenancy/organisations/', { key: 'anonymous||/tenancy/organisations/', url: '/tenancy/organisations/', data: {}, cachedAt: 1 })
    put('audity-offline-cache', 'org-1||/auth/profile/', { key: 'org-1||/auth/profile/', url: '/auth/profile/', data: { id: 'x' }, cachedAt: 1 })
    put('audity-local-store', 'org-1:runs:r1', { _key: 'org-1:runs:r1', _orgId: 'org-1', _entityType: 'runs', _recordId: 'r1', _isDeleted: false, id: 'r1' })
    put('audity-local-store', 'anonymous:accounts:a1', { _key: 'anonymous:accounts:a1', _orgId: 'anonymous', _entityType: 'accounts', _recordId: 'a1', _isDeleted: false, id: 'a1' })
  }
  const keys = (db: string) => [...(stores.get(db)?.keys() ?? [])].sort()

  it('with a known owner, entries are re-keyed to that owner and unsafe ones deleted', async () => {
    const { migrateLegacySavedData } = await import('@/lib/localDataGuard')
    seedLegacy()
    localStorage.setItem('audity:cache-owner-user-id', 'owner')
    expect(await migrateLegacySavedData()).toBe(true)
    expect(keys('audity-offline-cache')).toEqual(['org-1|owner||/payroll/runs/'])
    expect(keys('audity-local-store')).toEqual(['org-1~owner:runs:r1'])
    expect(stores.get('audity-local-store')!.get('org-1~owner:runs:r1')._orgId).toBe('org-1~owner')
    expect(localStorage.getItem('audity:saved-scope-v2')).toBe('1')
  })

  it('with an unknown owner, everything old is deleted', async () => {
    const { migrateLegacySavedData } = await import('@/lib/localDataGuard')
    seedLegacy()
    expect(await migrateLegacySavedData()).toBe(true)
    expect(keys('audity-offline-cache')).toEqual([])
    expect(keys('audity-local-store')).toEqual([])
  })

  it('runs only once', async () => {
    const { migrateLegacySavedData } = await import('@/lib/localDataGuard')
    localStorage.setItem('audity:saved-scope-v2', '1')
    seedLegacy()
    await migrateLegacySavedData()
    expect(keys('audity-offline-cache').length).toBe(3)
  })
})
