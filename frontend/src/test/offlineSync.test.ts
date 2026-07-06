/**
 * Offline sync lifecycle — integration tests.
 *
 * Covers the automatable half of docs/OFFLINE_FIELD_TEST.md (the vitest
 * harness can't toggle real connectivity or restart a Tauri process — those
 * steps live in the manual script):
 *
 *   1. Mutations queued offline survive an app "restart" (clearSession keeps
 *      the queue and the offline verifier) and flush EXACTLY ONCE after the
 *      next real-token login. No duplicates on repeat flushes.
 *   2. An offline grace session (PBKDF2 unlock, no tokens) never flushes —
 *      flushing without tokens would 401 every item into 'conflict'.
 *   3. Temp IDs from optimistic POSTs are rewritten in later queue items.
 *   4. A server 4xx marks the item 'conflict' (surfaced by SyncStatusBadge);
 *      retry() re-queues it, dismiss() drops it.
 *   5. A mid-flush network failure does NOT burn the retry budget and halts
 *      the flush (remaining items stay pending for the next reconnect).
 *   6. Flush is org-scoped: another org's queued items are never replayed
 *      into the active org's tenant.
 *   7. clearSession() preserves offline artifacts; logout() wipes them.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── In-memory IndexedDB fake (idb) ────────────────────────────────────────────
// One Map per database, persisting across "app restarts" within a test —
// exactly like real IndexedDB persists across Tauri process restarts.
const { idbStores } = vi.hoisted(() => ({ idbStores: new Map<string, Map<string, any>>() }))

vi.mock('idb', () => {
  const getStore = (db: string) => {
    if (!idbStores.has(db)) idbStores.set(db, new Map())
    return idbStores.get(db)!
  }
  return {
    openDB: vi.fn(async (name: string) => {
      const store = getStore(name)
      const keyOf = (v: any) => v.id ?? v.key // syncEngine keyPath: 'id'; offlineCache: 'key'
      return {
        getAll: async () => [...store.values()],
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

// ── api client mock ──────────────────────────────────────────────────────────
// syncEngine.flush() dynamically imports { api } and calls it per queue item.
// authStore.logout() dynamically imports { authApi } for verifier revocation.
const { apiCallable, revokeMock } = vi.hoisted(() => ({
  apiCallable: vi.fn(),
  revokeMock: vi.fn(async () => ({ data: {} })),
}))

vi.mock('@/services/api', () => ({
  api: (config: unknown) => apiCallable(config),
  authApi: {
    revokeOfflineVerifier: () => revokeMock(),
    getOfflineVerifierStatus: vi.fn(async () => ({ data: { active: true } })),
  },
}))

// localStore is exercised via flush's temp-ID resolution — spy on it.
const { localStoreMock } = vi.hoisted(() => ({
  localStoreMock: {
    upsert: vi.fn(async () => {}),
    upsertMany: vi.fn(async () => {}),
    remove: vi.fn(async () => {}),
    getAll: vi.fn(async () => []),
    replaceTempId: vi.fn(async () => {}),
    clearOrg: vi.fn(async () => {}),
    clearAll: vi.fn(async () => {}),
  },
}))
vi.mock('@/lib/localStore', () => ({ localStore: localStoreMock }))

vi.mock('@/lib/analytics', () => ({ resetAnalytics: vi.fn(), identifyUser: vi.fn() }))

vi.mock('react-hot-toast', () => ({
  default: Object.assign(vi.fn(), {
    loading: vi.fn(() => 'toast-id'),
    dismiss: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
  }),
}))

import { syncEngine } from '@/lib/syncEngine'
import { flushQueuedMutations } from '@/lib/syncFlush'
import { useAuthStore } from '@/store/authStore'
import type { OfflineVerifierBlob } from '@/lib/offlineVerifier'

// ── Helpers ──────────────────────────────────────────────────────────────────

const ORG_A = '11111111-1111-4111-8111-111111111111'
const ORG_B = '22222222-2222-4222-8222-222222222222'

const orgA = { id: ORG_A, name: 'Mama Chidinma Provisions', slug: 'mama-c', account_type: 'business', currency: 'NGN', country: 'NG' }

function loginToOrgA() {
  useAuthStore.getState().initSession(
    { id: 'u1', email: 'trader@example.com', first_name: 'Ada', last_name: 'O', phone: '', is_verified: true } as any,
    { access: 'header.payload.sig', refresh: 'refresh.token.x' } as any,
    orgA as any,
    [orgA] as any,
  )
}

function startGraceSession() {
  const blob = {
    algorithm: 'pbkdf2_sha256', iterations: 600_000, salt: 'c2FsdA==', hash: 'aGFzaA==',
    user_id: 'u1', email: 'trader@example.com', mfa_enabled: false, token_version: 1,
    issued_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 14 * 86400_000).toISOString(),
    organisations: [{ ...orgA, is_active: true, onboarding_completed: true }],
  } as unknown as OfflineVerifierBlob
  useAuthStore.getState().startOfflineSession(blob)
}

async function enqueueOfflineWork() {
  // What a trader does at the stall: 3 sales, a price edit, a customer cleanup.
  await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 4500 }, tempId: 'tmp_sale_1' })
  await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 1200 }, tempId: 'tmp_sale_2' })
  await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 800 }, tempId: 'tmp_sale_3' })
  await syncEngine.enqueue({ method: 'patch', url: `/inventory/products/33333333-3333-4333-8333-333333333333/`, data: { selling_price: '950' } })
  await syncEngine.enqueue({ method: 'delete', url: `/customers/44444444-4444-4444-8444-444444444444/` })
}

beforeEach(() => {
  idbStores.forEach((s) => s.clear())
  apiCallable.mockReset()
  revokeMock.mockClear()
  localStoreMock.replaceTempId.mockClear()
  localStorage.clear()
  useAuthStore.getState().clearSession()
})

// ── 1 + 2: the field scenario ────────────────────────────────────────────────

describe('offline field cycle: queue → restart → offline unlock → re-login → sync exactly once', () => {
  it('queued offline mutations survive restart and flush exactly once after re-login', async () => {
    // Day starts online: trader logs in
    loginToOrgA()

    // Internet dies; five mutations get queued
    await enqueueOfflineWork()
    expect(await syncEngine.pendingCount()).toBe(5)

    // ── App restart (startup guard runs clearSession, NOT logout) ──
    localStorage.setItem('audity-offline-verifier', 'encrypted-blob-sentinel')
    useAuthStore.getState().clearSession()
    await syncEngine.recoverStuck()

    // Queue and verifier both survived the restart
    expect(await syncEngine.pendingCount()).toBe(5)
    expect(localStorage.getItem('audity-offline-verifier')).toBe('encrypted-blob-sentinel')

    // ── Offline unlock (grace session, no tokens) ──
    startGraceSession()
    expect(useAuthStore.getState().isOfflineSession).toBe(true)
    expect(useAuthStore.getState().tokens).toBeNull()

    // A flush attempt during the grace session must be a no-op — flushing
    // without tokens would 401 all five items straight into 'conflict'.
    await flushQueuedMutations()
    expect(apiCallable).not.toHaveBeenCalled()
    expect(await syncEngine.pendingCount()).toBe(5)

    // ── Internet returns; trader re-authenticates online ──
    apiCallable.mockImplementation(async (config: any) => ({
      data: { id: crypto.randomUUID(), ...(typeof config.data === 'object' ? config.data : {}) },
      status: config.method === 'post' ? 201 : 200,
    }))
    loginToOrgA()
    expect(useAuthStore.getState().isOfflineSession).toBe(false)

    // Post-login flush (AppLayout mount effect calls this exact helper)
    await flushQueuedMutations()
    expect(apiCallable).toHaveBeenCalledTimes(5)
    expect(await syncEngine.pendingCount()).toBe(0)

    // Chronological replay: the three sales first, then edit, then delete
    const methods = apiCallable.mock.calls.map(([c]) => c.method)
    expect(methods).toEqual(['post', 'post', 'post', 'patch', 'delete'])
    // Replays carry the offline-retry marker so interceptors don't re-queue them
    for (const [cfg] of apiCallable.mock.calls) {
      expect(cfg.headers['X-Offline-Retry']).toBe('1')
    }

    // ── Exactly once: a second flush must not repeat anything ──
    await flushQueuedMutations()
    expect(apiCallable).toHaveBeenCalledTimes(5)
  })
})

// ── 3: temp-ID chain resolution ──────────────────────────────────────────────

describe('temp-ID rewrite', () => {
  it('rewrites later queue items that reference an optimistic POST temp ID', async () => {
    loginToOrgA()
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 100 }, tempId: 'tmp_abc' })
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/tmp_abc/pay/', data: { amount: 100, method: 'cash' } })

    const REAL_ID = '55555555-5555-4555-8555-555555555555'
    apiCallable.mockImplementation(async (config: any) =>
      config.method === 'post' && config.url === '/sales/invoices/'
        ? { data: { id: REAL_ID }, status: 201 }
        : { data: { id: REAL_ID, status: 'paid' }, status: 200 })

    await syncEngine.flush()

    expect(apiCallable).toHaveBeenCalledTimes(2)
    expect(apiCallable.mock.calls[1][0].url).toBe(`/sales/invoices/${REAL_ID}/pay/`)
    expect(localStoreMock.replaceTempId).toHaveBeenCalledWith(ORG_A, 'invoices', 'tmp_abc', REAL_ID)
  })
})

// ── 4: conflict surfacing + retry/dismiss ────────────────────────────────────

describe('conflict handling (SyncStatusBadge contract)', () => {
  it('marks 4xx as conflict, exposes it to subscribers, and supports retry + dismiss', async () => {
    loginToOrgA()
    await syncEngine.enqueue({ method: 'patch', url: '/inventory/products/66666666-6666-4666-8666-666666666666/', data: { selling_price: '10' } })

    // Server-side edit happened while offline → version check rejects with 409/4xx
    apiCallable.mockRejectedValueOnce({ response: { status: 409 }, message: 'conflict' })

    const seen: unknown[][] = []
    const unsub = syncEngine.subscribe((items) => seen.push(items.map((i) => i.status)))

    const { conflicts } = await syncEngine.flush()
    expect(conflicts).toBe(1)

    let items = await syncEngine.snapshot()
    expect(items[0].status).toBe('conflict')
    expect(items[0].lastError).toContain('409')
    // Badge subscribers were notified of the conflict state
    expect(seen.flat()).toContain('conflict')

    // Conflicts are NOT auto-retried by a later flush
    apiCallable.mockResolvedValue({ data: { id: 'x' }, status: 200 })
    await syncEngine.flush()
    expect(apiCallable).toHaveBeenCalledTimes(1)

    // Retry: back to pending, next flush replays it
    await syncEngine.retry(items[0].id)
    await syncEngine.flush()
    expect(apiCallable).toHaveBeenCalledTimes(2)
    expect(await syncEngine.pendingCount()).toBe(0)

    // Dismiss removes outright
    await syncEngine.enqueue({ method: 'delete', url: '/customers/77777777-7777-4777-8777-777777777777/' })
    items = await syncEngine.snapshot()
    await syncEngine.dismiss(items[0].id)
    expect((await syncEngine.snapshot()).length).toBe(0)

    unsub()
  })
})

// ── 5: network failure mid-flush ─────────────────────────────────────────────

describe('network failure mid-flush', () => {
  it('does not burn the retry budget and halts so later items are untouched', async () => {
    loginToOrgA()
    await enqueueOfflineWork() // 5 items

    // Wire drops on the first replay — no HTTP response at all
    apiCallable.mockRejectedValue(new Error('Network Error'))
    const { succeeded, conflicts } = await syncEngine.flush()

    expect(succeeded).toBe(0)
    expect(conflicts).toBe(0)
    // Halted after the first failure instead of timing out on all five
    expect(apiCallable).toHaveBeenCalledTimes(1)

    const items = await syncEngine.snapshot()
    expect(items.every((i) => i.status === 'pending')).toBe(true)
    // Retry budget untouched — flaky market internet must never strand a sale
    expect(items.every((i) => i.retries === 0)).toBe(true)

    // Connectivity returns → full recovery
    apiCallable.mockReset()
    apiCallable.mockImplementation(async () => ({ data: { id: crypto.randomUUID() }, status: 201 }))
    const second = await syncEngine.flush()
    expect(second.succeeded).toBe(5)
    expect(await syncEngine.pendingCount()).toBe(0)
  })
})

// ── 6: org scoping ───────────────────────────────────────────────────────────

describe('org-scoped flush', () => {
  it("never replays another organisation's queued items into the active org", async () => {
    loginToOrgA()
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: { total: 999 }, orgId: ORG_B })
    apiCallable.mockResolvedValue({ data: { id: 'x' }, status: 201 })

    const { succeeded } = await syncEngine.flush()
    expect(succeeded).toBe(0)
    expect(apiCallable).not.toHaveBeenCalled()
    expect(await syncEngine.pendingCount()).toBe(1) // still waiting for org B to become active

    // Switch to org B → item flushes
    useAuthStore.getState().setOrganisation({ ...orgA, id: ORG_B } as any)
    await syncEngine.flush()
    expect(apiCallable).toHaveBeenCalledTimes(1)
    expect(await syncEngine.pendingCount()).toBe(0)
  })
})

// ── 7: clearSession vs logout ────────────────────────────────────────────────

describe('clearSession vs logout — offline artifact lifecycle', () => {
  it('clearSession (startup guard / expiry / inactivity) keeps verifier + queue', async () => {
    loginToOrgA()
    localStorage.setItem('audity-offline-verifier', 'blob')
    localStorage.setItem('audity-offline-key', 'wrapper-key')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: {} })

    useAuthStore.getState().clearSession()

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(useAuthStore.getState().tokens).toBeNull()
    expect(localStorage.getItem('audity-offline-verifier')).toBe('blob')
    expect(localStorage.getItem('audity-offline-key')).toBe('wrapper-key')
    expect(await syncEngine.pendingCount()).toBe(1)
  })

  it('logout (explicit) wipes the verifier and revokes server-side, but keeps the queue', async () => {
    loginToOrgA()
    localStorage.setItem('audity-offline-verifier', 'blob')
    await syncEngine.enqueue({ method: 'post', url: '/sales/invoices/', data: {} })

    useAuthStore.getState().logout()
    // logout's verifier wipe runs through dynamic imports — let microtasks drain
    await vi.waitFor(() => {
      expect(localStorage.getItem('audity-offline-verifier')).toBeNull()
      expect(revokeMock).toHaveBeenCalled()
    })

    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    // Queued business data survives even explicit logout — flush is org-scoped,
    // so it can only ever sync back into the same organisation.
    expect(await syncEngine.pendingCount()).toBe(1)
  })
})
