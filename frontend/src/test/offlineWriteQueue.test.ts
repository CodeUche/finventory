/**
 * Through the REAL api client (with a fake network): a save that fails on the
 * wire while the device still believes it is online (the desktop WebView case:
 * navigator.onLine stays true) must be kept in the offline queue, under the
 * person who made it, and must not be visible to anyone else.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { stores } = vi.hoisted(() => ({ stores: new Map<string, Map<string, any>>() }))

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

import { AxiosError } from 'axios'
import { api } from '@/services/api'
import { syncEngine } from '@/lib/syncEngine'
import { retryPendingWipe } from '@/lib/localDataGuard'
import { useAuthStore } from '@/store/authStore'

const org1 = { id: 'org-1', name: 'One', slug: 'one', account_type: 'business', currency: 'NGN', country: 'NG' }
const signIn = (id: string) => useAuthStore.getState().initSession(
  { id, email: `${id}@example.com`, first_name: 'A', last_name: 'B', phone: '', is_verified: true } as any,
  { access: 'a.b.c', refresh: 'r' } as any, org1 as any, [org1] as any,
)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const queued = () => [...(stores.get('audity-sync-queue')?.values() ?? [])]

beforeEach(async () => {
  // The wire is cut: every request fails with a network error, but the
  // browser still reports it is online.
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  ;(api.defaults as any).adapter = (config: any) =>
    Promise.reject(new AxiosError('Network Error', 'ERR_NETWORK', config, null, undefined))
  await retryPendingWipe()
  stores.forEach((m) => m.clear())
  localStorage.clear()
  useAuthStore.getState().clearSession()
})

describe('a save that fails on the wire while the device thinks it is online', () => {
  it('is queued under the signed-in user and the person sees it as saved on the device', async () => {
    signIn('owner')
    await sleep(50)
    const res = await api.post('/sales/locations/', { name: 'Wire-cut branch' })
    expect(res.status).toBe(201)
    await sleep(100)
    const q = queued().filter((i) => i.url === '/sales/locations/')
    expect(q.length).toBe(1)
    expect(q[0].userId).toBe('owner')
    expect(q[0].method).toBe('post')
  })

  it('is hidden from another user who signs in afterwards, and kept for the owner', async () => {
    signIn('owner')
    await sleep(50)
    await api.post('/sales/locations/', { name: 'Wire-cut branch' })
    await sleep(100)
    useAuthStore.getState().logout()
    await sleep(100)
    signIn('staff')
    await sleep(100)
    expect((await syncEngine.snapshot()).length).toBe(0)
    expect(await syncEngine.pendingCount()).toBe(0)
    expect(queued().filter((i) => i.url === '/sales/locations/').length).toBe(1) // still on the device
  })

  it('also works for a sale', async () => {
    signIn('owner')
    await sleep(50)
    const res = await api.post('/sales/invoices/', { total: '4500.00' })
    expect(res.status).toBe(201)
    await sleep(100)
    expect(queued().filter((i) => i.url === '/sales/invoices/' && i.userId === 'owner').length).toBe(1)
  })
})
