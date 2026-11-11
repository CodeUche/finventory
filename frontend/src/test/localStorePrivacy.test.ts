/**
 * Privacy: saved copies of business data must not outlive the person who
 * loaded them. Covers the local entity store (IndexedDB 'audity-local-store'),
 * the response cache, and the unsent-changes queue.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// In-memory IndexedDB fake: one Map per database, like the real thing it
// survives for the whole test, so "what is still on disk" can be inspected.
const { idbStores } = vi.hoisted(() => ({ idbStores: new Map<string, Map<string, any>>() }))

vi.mock('idb', () => {
  const getStore = (db: string) => {
    if (!idbStores.has(db)) idbStores.set(db, new Map())
    return idbStores.get(db)!
  }
  return {
    openDB: vi.fn(async (name: string) => {
      const store = getStore(name)
      const keyOf = (v: any) => v._key ?? v.id ?? v.key
      return {
        getAll: async () => [...store.values()],
        getAllFromIndex: async (_s: string, _i: string, [o, t]: [string, string]) =>
          [...store.values()].filter((v) => v._orgId === o && v._entityType === t),
        get: async (_s: string, key: string) => store.get(key),
        put: async (_s: string, value: any) => { store.set(keyOf(value), value) },
        delete: async (_s: string, key: string) => { store.delete(key) },
        clear: async () => { store.clear() },
        transaction: () => ({
          store: {
            put: (v: any) => { store.set(keyOf(v), v) },
            delete: (k: string) => { store.delete(k) },
          },
          done: Promise.resolve(),
        }),
        objectStoreNames: { contains: () => true },
      }
    }),
  }
})

const { apiCallable } = vi.hoisted(() => ({ apiCallable: vi.fn() }))
vi.mock('@/services/api', () => ({
  api: (config: unknown) => apiCallable(config),
  authApi: { revokeOfflineVerifier: vi.fn(async () => ({ data: {} })) },
}))
vi.mock('@/lib/analytics', () => ({ resetAnalytics: vi.fn(), identifyUser: vi.fn() }))

import { localStore } from '@/lib/localStore'
import { offlineCache } from '@/lib/offlineCache'
import { syncEngine } from '@/lib/syncEngine'
import { claimCacheForUser, clearLocalReadData } from '@/lib/cacheOwner'
import { useAuthStore } from '@/store/authStore'

const ORG = '11111111-1111-4111-8111-111111111111'
const org = { id: ORG, name: 'Mama C', slug: 'mama-c', account_type: 'business', currency: 'NGN', country: 'NG' }

function signIn(id: string) {
  useAuthStore.getState().initSession(
    { id, email: `${id}@example.com`, first_name: 'X', last_name: 'Y', phone: '', is_verified: true } as any,
    { access: 'a.b.c', refresh: 'r' } as any,
    org as any,
    [org] as any,
  )
}

async function seedOwnerData() {
  await localStore.upsert(ORG, 'customers', 'c1', { id: 'c1', name: 'Big Customer' })
  await localStore.upsert(ORG, 'invoices', 'i1', { id: 'i1', total: '4500.00' })
  await offlineCache.set('/customers/', { results: [{ id: 'c1' }] })
}
const entityCount = async () => (await localStore.getAll(ORG, 'customers')).length + (await localStore.getAll(ORG, 'invoices')).length
const settle = () => new Promise((r) => setTimeout(r, 20))

function setOnline(v: boolean) {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(v)
}

beforeEach(() => {
  // Empty each database in place: the modules keep their open handle between tests.
  idbStores.forEach((m) => m.clear())
  localStorage.clear()
  useAuthStore.getState().clearSession()
  apiCallable.mockReset()
  setOnline(true)
})
afterEach(() => { vi.restoreAllMocks() })

describe('entity store is wiped', () => {
  it('on logout', async () => {
    signIn('owner')
    await settle()
    await seedOwnerData()
    expect(await entityCount()).toBe(2)

    useAuthStore.getState().logout()
    await vi.waitFor(async () => { expect(await entityCount()).toBe(0) })
    expect(await offlineCache.get('/customers/')).toBeNull()
  })

  it('when a different user signs in', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()
    await claimCacheForUser('staff')
    expect(await entityCount()).toBe(0)
    expect(await offlineCache.get('/customers/')).toBeNull()
  })

  it('also when a different user signs in while offline (owner is known)', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()
    setOnline(false)
    await claimCacheForUser('staff')
    expect(await entityCount()).toBe(0)
  })

  it('is kept when the same user signs in again', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()
    await claimCacheForUser('owner')
    expect(await entityCount()).toBe(2)
  })

  it('is kept when the owner is unknown and the device is offline', async () => {
    await seedOwnerData()
    setOnline(false)
    await claimCacheForUser('someone')
    expect(await entityCount()).toBe(2)
    // owner left unset so the next online sign-in decides
    expect(localStorage.getItem('audity:cache-owner-user-id')).toBeNull()
  })

  it('is cleared when the owner is unknown and the device is online', async () => {
    await seedOwnerData()
    await claimCacheForUser('someone')
    expect(await entityCount()).toBe(0)
  })

  it('never throws when IndexedDB is unavailable', async () => {
    const idb = await import('idb')
    vi.mocked(idb.openDB).mockRejectedValue(new Error('IndexedDB blocked'))
    await expect(clearLocalReadData()).resolves.toBeUndefined()
  })
})

describe('unsent offline changes (sync queue)', () => {
  it('survive logout and are only visible to the user who made them', async () => {
    signIn('owner')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 100 }, tempId: 'tmp_1' })
    expect(await syncEngine.pendingCount()).toBe(1)

    useAuthStore.getState().logout()
    await settle()
    expect(idbStores.get('audity-sync-queue')?.size).toBe(1) // still on disk

    await claimCacheForUser('staff')
    signIn('staff')
    expect(await syncEngine.pendingCount()).toBe(0)
    expect((await syncEngine.snapshot()).length).toBe(0)
    const res = await syncEngine.flush()
    expect(res.succeeded).toBe(0)
    expect(apiCallable).not.toHaveBeenCalled()
  })

  it('come back and are sent when the same user signs in again', async () => {
    signIn('owner')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 100 }, tempId: 'tmp_1' })
    useAuthStore.getState().logout()
    await settle()

    signIn('owner')
    expect(await syncEngine.pendingCount()).toBe(1)
  })

  it('old items with no owner go to the previous user, not the new one', async () => {
    await syncEngine.pendingCount() // opens the queue database
    idbStores.get('audity-sync-queue')!.set('old', {
      id: 'old', method: 'post', url: '/sales/invoices/', timestamp: 1, label: 'x',
      status: 'pending', retries: 0, orgId: ORG,
    })
    await claimCacheForUser('owner')           // adopts to owner (owner unknown, online)
    await claimCacheForUser('staff')           // different user
    signIn('staff')
    expect(await syncEngine.pendingCount()).toBe(0)
    signIn('owner')
    expect(await syncEngine.pendingCount()).toBe(1)
  })
})
