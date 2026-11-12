/**
 * A database that hangs (held open by another tab) must never freeze reads or
 * block later wipes: reads return nothing after a short limit, the wipe stays
 * owed, and a later start retries it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { stores, knobs } = vi.hoisted(() => ({
  stores: new Map<string, Map<string, any>>(),
  knobs: { hangClear: false, hangGetAll: false, getAllDelayMs: 0 },
}))

vi.mock('idb', () => ({
  openDB: vi.fn(async (name: string) => {
    if (!stores.has(name)) stores.set(name, new Map())
    const store = stores.get(name)!
    const keyOf = (v: any) => v._key ?? v.id ?? v.key
    return {
      close: () => {},
      getAll: async () => {
        if (knobs.hangGetAll) return new Promise<any[]>(() => {})
        const snapshot = [...store.values()] // read first, answer late (like a slow disk)
        if (knobs.getAllDelayMs) await new Promise((r) => setTimeout(r, knobs.getAllDelayMs))
        return snapshot
      },
      getAllFromIndex: async (_s: string, _i: string, [o, t]: [string, string]) =>
        [...store.values()].filter((v) => v._orgId === o && v._entityType === t),
      get: async (_s: string, k: string) => store.get(k),
      put: async (_s: string, v: any) => { store.set(keyOf(v), v) },
      delete: async (_s: string, k: string) => { store.delete(k) },
      clear: () => (knobs.hangClear ? new Promise<void>(() => {}) : Promise.resolve(void store.clear())),
      objectStoreNames: { contains: () => true },
    }
  }),
}))
vi.mock('@/lib/dialog', () => ({ alertDialog: vi.fn(async () => {}) }))

import { localStore } from '@/lib/localStore'
import { offlineCache } from '@/lib/offlineCache'
import { clearLocalReadData } from '@/lib/cacheOwner'
import { migrateLegacySavedData } from '@/lib/localDataGuard'
import { isWipePending, retryPendingWipe, wipeTimeouts } from '@/lib/localDataGuard'
import { useAuthStore } from '@/store/authStore'

const PENDING = 'audity:wipe-pending'
const ORG = 'org-1'
const size = (n: string) => stores.get(n)?.size ?? 0
const org = { id: ORG, name: 'O', slug: 'o', account_type: 'business', currency: 'NGN', country: 'NG' }
const signIn = () => useAuthStore.getState().initSession(
  { id: 'u1', email: 'u1@example.com', first_name: 'A', last_name: 'B', phone: '', is_verified: true } as any,
  { access: 'a.b.c', refresh: 'r' } as any, org as any, [org] as any,
)

beforeEach(async () => {
  knobs.hangClear = false
  knobs.hangGetAll = false
  knobs.getAllDelayMs = 0
  signIn()
  vi.stubGlobal('indexedDB', {
    deleteDatabase: () => { const r: any = {}; setTimeout(() => r.onblocked?.(), 0); return r }, // never finishes
  })
  Object.assign(wipeTimeouts, { read: 40, step: 40 })
  await retryPendingWipe()
  stores.forEach((m) => m.clear())
  localStorage.clear()
})
afterEach(() => { vi.unstubAllGlobals() })

describe('a database that hangs', () => {
  it('reads return nothing within the limit instead of waiting forever, and the wipe stays owed', async () => {
    await localStore.upsert(ORG, 'customers', 'c1', { id: 'c1' })
    await offlineCache.set('/customers/', { results: [] })
    knobs.hangClear = true

    const wipe = clearLocalReadData()
    const started = Date.now()
    expect(await localStore.getAll(ORG, 'customers')).toEqual([])
    expect(await offlineCache.get('/customers/')).toBeNull()
    expect(Date.now() - started).toBeLessThan(1000)
    expect(localStorage.getItem(PENDING)).toBe('1')

    expect(await wipe).toBe(false) // the hung clear counted as a failure
    expect(isWipePending()).toBe(true)
    expect(size('audity-local-store')).toBe(1) // still on disk, still unreadable
  })

  it('a later wipe is not stuck behind the hung one, and the next start finishes the job', async () => {
    await localStore.upsert(ORG, 'customers', 'c1', { id: 'c1' })
    knobs.hangClear = true
    const first = clearLocalReadData()
    const second = clearLocalReadData() // must not queue behind `first`
    expect(await Promise.all([first, second])).toEqual([false, false])
    expect(localStorage.getItem(PENDING)).toBe('1')

    knobs.hangClear = false // the other tab let go; app is started again
    expect(await retryPendingWipe()).toBe(true)
    expect(localStorage.getItem(PENDING)).toBeNull()
    expect(size('audity-local-store')).toBe(0)
  })
})

describe('one-time cleanup of old entries is bounded and safe', () => {
  const OWNER = 'audity:cache-owner-user-id'
  const DONE = 'audity:saved-scope-v2'
  const seedLegacy = () => {
    for (const [db, key, v] of [
      ['audity-offline-cache', 'org-1||/payroll/runs/', { key: 'org-1||/payroll/runs/', url: '/payroll/runs/', data: {}, cachedAt: 1 }],
      ['audity-local-store', 'org-1:runs:r1', { _key: 'org-1:runs:r1', _orgId: 'org-1', _entityType: 'runs', _recordId: 'r1', _isDeleted: false, id: 'r1' }],
    ] as Array<[string, string, Record<string, unknown>]>) {
      if (!stores.has(db)) stores.set(db, new Map())
      stores.get(db)!.set(key, v)
    }
  }
  const keys = (db: string) => [...(stores.get(db)?.keys() ?? [])]

  it('a timeout means "not finished": no done mark, and reads stop paying the wait', async () => {
    await offlineCache.get('/x/') // opens the databases
    seedLegacy()
    localStorage.setItem(OWNER, 'u1')
    knobs.hangGetAll = true
    expect(await migrateLegacySavedData()).toBe(false)
    expect(localStorage.getItem(DONE)).toBeNull() // retried next start
    knobs.hangGetAll = false
    const t = Date.now()
    await localStore.getAll(ORG, 'runs')
    expect(Date.now() - t).toBeLessThan(wipeTimeouts.read) // nobody is waiting on the dead migration
  })

  it('with a wipe owed, old entries are deleted instead of re-keyed', async () => {
    await offlineCache.get('/x/')
    seedLegacy()
    localStorage.setItem(OWNER, 'u1') // the marker can be set while a wipe never happened
    localStorage.setItem('audity:wipe-pending', '1')
    expect(await migrateLegacySavedData()).toBe(true)
    expect(keys('audity-offline-cache')).toEqual([])
    expect(keys('audity-local-store')).toEqual([])
  })

  it('a wipe during the migration leaves nothing behind', async () => {
    await offlineCache.get('/x/')
    seedLegacy()
    localStorage.setItem(OWNER, 'u1')
    knobs.getAllDelayMs = 60
    const migration = migrateLegacySavedData() // slow: still reading when the wipe starts
    const wipe = clearLocalReadData()
    await Promise.all([migration, wipe])
    await new Promise((r) => setTimeout(r, 200))
    expect(keys('audity-offline-cache')).toEqual([])
    expect(keys('audity-local-store')).toEqual([])
  })
})
