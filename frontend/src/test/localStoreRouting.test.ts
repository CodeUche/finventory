/**
 * Through the REAL api client (with a fake network):
 *  - two people asking for the same URL never share one in-flight request;
 *  - a late answer is filed under the business the request was made for, even
 *    if the user switched business before it arrived.
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

import { api } from '@/services/api'
import { retryPendingWipe } from '@/lib/localDataGuard'
import { useAuthStore } from '@/store/authStore'

const org1 = { id: 'org-1', name: 'One', slug: 'one', account_type: 'business', currency: 'NGN', country: 'NG' }
const org2 = { id: 'org-2', name: 'Two', slug: 'two', account_type: 'business', currency: 'NGN', country: 'NG' }
const signIn = (id: string) => useAuthStore.getState().initSession(
  { id, email: `${id}@example.com`, first_name: 'A', last_name: 'B', phone: '', is_verified: true } as any,
  { access: 'a.b.c', refresh: 'r' } as any, org1 as any, [org1, org2] as any,
)
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

interface Call { url: string; answer: (data: unknown) => void }
let calls: Call[] = []
const only = (url: string) => calls.filter((c) => c.url === url) // sign-out also makes its own calls

beforeEach(async () => {
  calls = []
  ;(api.defaults as any).adapter = (config: any) => new Promise((resolve) => {
    calls.push({
      url: config.url,
      answer: (data) => resolve({ data, status: 200, statusText: 'OK', headers: {}, config }),
    })
  })
  await retryPendingWipe()
  stores.forEach((m) => m.clear())
  localStorage.clear()
  useAuthStore.getState().clearSession()
})

describe('shared in-flight requests', () => {
  it('a second user asking for the same URL does not receive the first user\'s answer', async () => {
    signIn('owner')
    await sleep(30)
    const forOwner = api.get('/auth/profile/')
    await sleep(20)
    expect(only('/auth/profile/').length).toBe(1)

    useAuthStore.getState().logout()
    signIn('staff')
    await sleep(30)
    const forStaff = api.get('/auth/profile/')
    await sleep(20)
    expect(only('/auth/profile/').length).toBe(2) // staff made their own request

    only('/auth/profile/')[1].answer({ id: 'staff' })
    expect(((await forStaff).data as { id: string }).id).toBe('staff')
    only('/auth/profile/')[0].answer({ id: 'owner' })
    await forOwner.catch(() => {})
  })

  it('the same user asking twice still shares one request', async () => {
    signIn('owner')
    await sleep(30)
    const a = api.get('/auth/profile/')
    const b = api.get('/auth/profile/')
    await sleep(20)
    expect(only('/auth/profile/').length).toBe(1)
    only('/auth/profile/')[0].answer({ id: 'owner' })
    expect(((await a).data as { id: string }).id).toBe('owner')
    expect(((await b).data as { id: string }).id).toBe('owner')
  })

  it('waiters on a request from before sign-out are released, not left to hang', async () => {
    signIn('owner')
    await sleep(30)
    const first = api.get('/payroll/runs/')
    await sleep(20)
    const waiter = api.get('/payroll/runs/') // joins the first
    await sleep(20)
    useAuthStore.getState().logout()
    await expect(waiter).rejects.toBeTruthy()
    only('/payroll/runs/')[0].answer({ results: [] })
    await first.catch(() => {})
  })
})

describe('late answers are filed under the business they were asked for', () => {
  it('after the user switches business, the answer is not filed under the new one', async () => {
    signIn('owner')
    await sleep(30)
    const pending = api.get('/payroll/employees/')
    await sleep(20)
    useAuthStore.getState().setOrganisation(org2 as any) // switch business
    only('/payroll/employees/')[0].answer({ results: [{ id: 'e1', name: 'Emp' }] })
    await pending
    await sleep(30)

    const cacheKeys = [...(stores.get('audity-offline-cache')?.keys() ?? [])]
    expect(cacheKeys.length).toBeGreaterThan(0)
    expect(cacheKeys.every((k) => k.startsWith('org-1|owner||'))).toBe(true)
    const records = [...(stores.get('audity-local-store')?.values() ?? [])]
    expect(records.length).toBe(1)
    expect(records[0]._orgId).toBe('org-1~owner')
  })
})
