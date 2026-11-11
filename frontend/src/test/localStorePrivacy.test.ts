/**
 * Privacy: saved copies of business data must not outlive the person who
 * loaded them. Covers the local entity store (IndexedDB 'audity-local-store'),
 * the response cache, the unsent-changes queue, failed wipes, and races.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// In-memory IndexedDB fake: one Map per database. Knobs let tests make
// clear() fail or be slow, like a database blocked by another tab.
const { idbStores, knobs } = vi.hoisted(() => ({
  idbStores: new Map<string, Map<string, any>>(),
  knobs: { failClear: false, clearDelayMs: 0 },
}))

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
        close: () => {},
        getAll: async () => [...store.values()],
        getAllFromIndex: async (_s: string, _i: string, [o, t]: [string, string]) =>
          [...store.values()].filter((v) => v._orgId === o && v._entityType === t),
        get: async (_s: string, key: string) => store.get(key),
        put: async (_s: string, value: any) => { store.set(keyOf(value), value) },
        delete: async (_s: string, key: string) => { store.delete(key) },
        clear: async () => {
          if (knobs.clearDelayMs) await new Promise((r) => setTimeout(r, knobs.clearDelayMs))
          if (knobs.failClear) throw new Error('database is locked')
          store.clear()
        },
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

const { apiCallable, alertMock } = vi.hoisted(() => ({ apiCallable: vi.fn(), alertMock: vi.fn(async (_message: string) => {}) }))
vi.mock('@/services/api', () => ({
  api: (config: unknown) => apiCallable(config),
  authApi: { revokeOfflineVerifier: vi.fn(async () => ({ data: {} })) },
}))
vi.mock('@/lib/analytics', () => ({ resetAnalytics: vi.fn(), identifyUser: vi.fn() }))
vi.mock('@/lib/dialog', () => ({ alertDialog: alertMock }))

import { localStore } from '@/lib/localStore'
import { offlineCache } from '@/lib/offlineCache'
import { syncEngine } from '@/lib/syncEngine'
import { claimCacheForUser, clearLocalReadData } from '@/lib/cacheOwner'
import { getGeneration, isWipePending, retryPendingWipe } from '@/lib/localDataGuard'
import { heldBasketsKey } from '@/lib/localUserData'
import { useAuthStore } from '@/store/authStore'

const ORG = '11111111-1111-4111-8111-111111111111'
const org = { id: ORG, name: 'Mama C', slug: 'mama-c', account_type: 'business', currency: 'NGN', country: 'NG' }
const PENDING = 'audity:wipe-pending'

function signIn(id: string) {
  useAuthStore.getState().initSession(
    { id, email: `${id}@example.com`, first_name: 'X', last_name: 'Y', phone: '', is_verified: true } as any,
    { access: 'a.b.c', refresh: 'r' } as any,
    org as any,
    [org] as any,
  )
}

async function seedOwnerData() {
  // Saved data is only ever written for a signed-in user.
  if (!useAuthStore.getState().isAuthenticated) signIn('owner')
  await localStore.upsert(ORG, 'customers', 'c1', { id: 'c1', name: 'Big Customer' })
  await localStore.upsert(ORG, 'invoices', 'i1', { id: 'i1', total: '4500.00' })
  await offlineCache.set('/customers/', { results: [{ id: 'c1' }] })
}
const entityCount = async () => (await localStore.getAll(ORG, 'customers')).length + (await localStore.getAll(ORG, 'invoices')).length
const onDisk = (db: string) => idbStores.get(db)?.size ?? 0
const settle = () => new Promise((r) => setTimeout(r, 20))
const setOnline = (v: boolean) => { vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(v) }

/** Pretend indexedDB.deleteDatabase either works or fails (the fallback path). */
function stubDeleteDatabase(works: boolean) {
  vi.stubGlobal('indexedDB', {
    deleteDatabase: (name: string) => {
      const req: any = {}
      setTimeout(() => {
        if (works) { idbStores.get(name)?.clear(); req.onsuccess?.() } else req.onerror?.()
      }, 0)
      return req
    },
  })
}

beforeEach(async () => {
  knobs.failClear = false
  knobs.clearDelayMs = 0
  vi.unstubAllGlobals()
  stubDeleteDatabase(false)
  await retryPendingWipe() // leave no owed wipe behind from an earlier test
  // Empty each database in place: the modules keep their open handle between tests.
  idbStores.forEach((m) => m.clear())
  localStorage.clear()
  useAuthStore.getState().clearSession()
  apiCallable.mockReset()
  alertMock.mockClear()
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
    expect(localStorage.getItem(PENDING)).toBeNull()
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
    setOnline(false)
    await seedOwnerData() // offline sign-in with no known owner: no wipe, owner stays unset
    useAuthStore.getState().clearSession()
    await claimCacheForUser('someone')
    expect(onDisk('audity-local-store')).toBe(2) // kept on disk
    // owner left unset so the next online sign-in decides
    expect(localStorage.getItem('audity:cache-owner-user-id')).toBeNull()
  })

  it('is cleared when the owner is unknown and the device is online', async () => {
    await seedOwnerData()
    await claimCacheForUser('someone')
    expect(await entityCount()).toBe(0)
  })
})

describe('a wipe that fails', () => {
  it('stays owed, blocks reads, and is retried', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()

    knobs.failClear = true
    const ok = await clearLocalReadData() // clear() throws and deleteDatabase fails
    expect(ok).toBe(false)
    expect(localStorage.getItem(PENDING)).toBe('1')
    expect(isWipePending()).toBe(true)
    // The data is still on disk, but nothing may read it.
    expect(onDisk('audity-local-store')).toBe(2)
    expect(await localStore.getAll(ORG, 'customers')).toEqual([])
    expect(await localStore.getOne(ORG, 'customers', 'c1')).toBeNull()
    expect(await offlineCache.get('/customers/')).toBeNull()
    // Writes are dropped too while the wipe is owed.
    await localStore.upsert(ORG, 'customers', 'c2', { id: 'c2' })
    expect(onDisk('audity-local-store')).toBe(2)

    // Next start-up / sign-in retries and finishes it.
    knobs.failClear = false
    expect(await retryPendingWipe()).toBe(true)
    expect(localStorage.getItem(PENDING)).toBeNull()
    expect(onDisk('audity-local-store')).toBe(0)
    expect(onDisk('audity-offline-cache')).toBe(0)
  })

  it('is retried by the next sign-in, even by the same user', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()
    knobs.failClear = true
    await clearLocalReadData()
    knobs.failClear = false
    await claimCacheForUser('owner')
    expect(localStorage.getItem(PENDING)).toBeNull()
    expect(onDisk('audity-local-store')).toBe(0)
  })

  it('falls back to deleting the database when clear() fails', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()
    knobs.failClear = true
    stubDeleteDatabase(true)
    expect(await clearLocalReadData()).toBe(true)
    expect(localStorage.getItem(PENDING)).toBeNull()
    expect(onDisk('audity-local-store')).toBe(0)
  })

  it('tells the user in plain words when an explicit logout cannot finish', async () => {
    signIn('owner')
    await settle()
    await seedOwnerData()
    knobs.failClear = true
    useAuthStore.getState().logout()
    await vi.waitFor(() => { expect(alertMock).toHaveBeenCalledTimes(1) })
    expect(alertMock.mock.calls[0][0]).toBe(
      'We could not clear saved data on this device. Close the app and sign in again to finish.',
    )
  })
})

describe('races and stale writes', () => {
  it('reads wait for a wipe that is still running', async () => {
    await claimCacheForUser('owner')
    await seedOwnerData()

    knobs.clearDelayMs = 40
    const wipe = claimCacheForUser('staff') // starts a slow wipe
    const read = localStore.getAll(ORG, 'customers') // staff reads straight away
    const cacheRead = offlineCache.get('/customers/')
    expect(await read).toEqual([])
    expect(await cacheRead).toBeNull()
    // By the time the read answered, the old data was really gone.
    expect(onDisk('audity-local-store')).toBe(0)
    await wipe
  })

  it('a write that started before the user changed is dropped', async () => {
    await claimCacheForUser('owner')
    const startedAt = getGeneration() // the owner's request begins
    await claimCacheForUser('staff') // user changes; wipe finishes
    signIn('staff')
    await localStore.upsert(ORG, 'customers', 'late', { id: 'late', name: 'Owner late reply' }, startedAt)
    await localStore.upsertMany(ORG, 'customers', [{ id: 'late2' }], 'id', startedAt)
    await offlineCache.set('/customers/', { results: [] }, startedAt)
    expect(onDisk('audity-local-store')).toBe(0)
    expect(onDisk('audity-offline-cache')).toBe(0)
    // A write that began under the current user is kept.
    await localStore.upsert(ORG, 'customers', 'ok', { id: 'ok' }, getGeneration())
    expect(onDisk('audity-local-store')).toBe(1)
  })

  it('a flush stops when the signed-in user changes mid-way', async () => {
    signIn('owner')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { n: 1 }, tempId: 'tmp_1' })
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { n: 2 }, tempId: 'tmp_2' })
    apiCallable.mockImplementation(async () => {
      signIn('staff') // the owner is replaced while the first request is in flight
      return { data: { id: 'real-1' } }
    })
    await syncEngine.flush()
    expect(apiCallable).toHaveBeenCalledTimes(1) // the second item was never sent
    // And nothing the owner's reply carried was written for the new user.
    expect(await localStore.getAll(ORG, 'invoices')).toEqual([])
  })
})

describe('unsent offline changes (sync queue)', () => {
  it('survive logout and are only visible to the user who made them', async () => {
    signIn('owner')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 100 }, tempId: 'tmp_1' })
    expect(await syncEngine.pendingCount()).toBe(1)

    useAuthStore.getState().logout()
    await settle()
    expect(onDisk('audity-sync-queue')).toBe(1) // still on disk

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

  it('show nothing at all when nobody is signed in', async () => {
    signIn('owner')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: {}, tempId: 'tmp_1' })
    useAuthStore.getState().clearSession()
    expect(await syncEngine.snapshot()).toEqual([])
    expect(await syncEngine.pendingCount()).toBe(0)
    expect(onDisk('audity-sync-queue')).toBe(1)
  })

  const ownerless = {
    id: 'old', method: 'post', url: '/sales/invoices/', timestamp: 1, label: 'x',
    status: 'pending', retries: 0, orgId: ORG,
  }

  it('old items with no owner go to the previous user when that is known', async () => {
    await claimCacheForUser('owner')
    await syncEngine.pendingCount() // opens the queue database
    idbStores.get('audity-sync-queue')!.set('old', { ...ownerless })
    await claimCacheForUser('staff')
    signIn('staff')
    expect(await syncEngine.pendingCount()).toBe(0)
    signIn('owner')
    expect(await syncEngine.pendingCount()).toBe(1)
  })

  it('old items with no known owner stay hidden from whoever signs in first', async () => {
    await syncEngine.pendingCount()
    idbStores.get('audity-sync-queue')!.set('old', { ...ownerless })
    await claimCacheForUser('first')
    signIn('first')
    expect(await syncEngine.pendingCount()).toBe(0)
    expect(onDisk('audity-sync-queue')).toBe(1) // kept, not destroyed
  })
})

describe('per-user leftovers in localStorage', () => {
  const MEDIA = `audity-media:${ORG}`
  const media = () => JSON.parse(localStorage.getItem(MEDIA) ?? '{}')

  it('the same user keeps their picture across logout and sign-in; logo and stamp stay', async () => {
    signIn('owner')
    useAuthStore.getState().setLogoDataUrl('L')
    useAuthStore.getState().setStampDataUrl('S')
    useAuthStore.getState().setAvatarDataUrl('A')
    expect(media().avatarOwnerId).toBe('owner')

    useAuthStore.getState().logout()
    await settle()
    expect(media().avatarDataUrl).toBe('A') // not deleted on a plain logout

    signIn('owner')
    expect(useAuthStore.getState().avatarDataUrl).toBe('A')
    expect(useAuthStore.getState().logoDataUrl).toBe('L')
    expect(useAuthStore.getState().stampDataUrl).toBe('S')
  })

  it('a different user never sees it, and it is deleted when they sign in', async () => {
    signIn('owner')
    useAuthStore.getState().setLogoDataUrl('L')
    useAuthStore.getState().setAvatarDataUrl('A')
    useAuthStore.getState().logout()
    await settle()

    signIn('staff')
    expect(useAuthStore.getState().avatarDataUrl).toBeNull()
    expect(useAuthStore.getState().logoDataUrl).toBe('L') // business-wide
    expect(media()).toEqual({ logoDataUrl: 'L' })
    // and the owner does not get it back later
    signIn('owner')
    expect(useAuthStore.getState().avatarDataUrl).toBeNull()
  })

  it('an old untagged picture goes to the previous owner if known, and is never shown to another user', async () => {
    await claimCacheForUser('owner')
    localStorage.setItem(MEDIA, JSON.stringify({ logoDataUrl: 'L', avatarDataUrl: 'OLD' }))
    signIn('owner') // same user: picture adopted as theirs
    expect(useAuthStore.getState().avatarDataUrl).toBe('OLD')
    useAuthStore.getState().logout()
    await settle()
    signIn('staff')
    expect(useAuthStore.getState().avatarDataUrl).toBeNull()
    expect(media().avatarDataUrl).toBeUndefined()
  })

  it('an old untagged picture with an unknown owner is not shown, and dropped on the next user change', async () => {
    localStorage.setItem(MEDIA, JSON.stringify({ avatarDataUrl: 'OLD' }))
    setOnline(false)
    signIn('someone') // offline + unknown owner: no wipe, but the picture stays hidden
    expect(useAuthStore.getState().avatarDataUrl).toBeNull()
    useAuthStore.getState().logout()
    await settle()
    setOnline(true)
    signIn('other')
    expect(media().avatarDataUrl).toBeUndefined()
  })

  it('logout removes the old retired queue key', async () => {
    signIn('owner')
    localStorage.setItem('finventory_offline_queue', '[]')
    useAuthStore.getState().logout()
    expect(localStorage.getItem('finventory_offline_queue')).toBeNull()
  })

  it('a different user does not get the previous users held baskets; the same user keeps theirs', async () => {
    await claimCacheForUser('owner')
    localStorage.setItem(heldBasketsKey(ORG, 'owner'), '[{"id":"b1"}]')
    await claimCacheForUser('owner') // same user again
    expect(localStorage.getItem(heldBasketsKey(ORG, 'owner'))).not.toBeNull()
    await claimCacheForUser('staff')
    expect(localStorage.getItem(heldBasketsKey(ORG, 'owner'))).toBeNull()
  })
})
