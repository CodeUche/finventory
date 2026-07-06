/**
 * Silent session resume — password-wrapped refresh token.
 *
 * Verifies the security properties, not just the happy path:
 *   • stash at online login → unlock with the password offline → silent
 *     resume upgrades the grace session in place (no re-login) and rotates
 *     the stored copy
 *   • the WRONG password can never unwrap the token (AES-GCM auth)
 *   • without an unlock, resume is impossible (nothing usable in memory)
 *   • clearSession drops the in-memory secrets — the password is required
 *     again after any session teardown — but keeps the disk blob
 *   • a dead token (401 — expired/blacklisted/password changed) deletes the
 *     blob and falls back to the banner flow
 *   • destroying the verifier destroys the wrapped refresh token with it
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }))

vi.mock('@/services/api', () => ({
  api: { post: (url: string, data: unknown) => postMock(url, data) },
  authApi: { revokeOfflineVerifier: vi.fn(async () => ({ data: {} })) },
}))
vi.mock('@/lib/analytics', () => ({ resetAnalytics: vi.fn(), identifyUser: vi.fn() }))
// offlineCache is dynamically imported by logout(); stub it so no IDB is needed
vi.mock('@/lib/offlineCache', () => ({ offlineCache: { clearAll: vi.fn(async () => {}) } }))

import {
  stashRefreshAtLogin, unlockRefreshOffline, trySilentResume,
  clearResumeMemory, deleteStoredRefresh,
} from '@/lib/offlineResume'
import { deleteVerifier } from '@/lib/offlineVerifier'
import { useAuthStore } from '@/store/authStore'
import type { OfflineVerifierBlob } from '@/lib/offlineVerifier'

const EMAIL = 'trader@example.com'
const PASSWORD = 'CorrectHorse9!'
const ORG = { id: '11111111-1111-4111-8111-111111111111', name: 'Stall 14', slug: 's14', account_type: 'business', currency: 'NGN', country: 'NG' }
const REFRESH_KEY = 'audity-offline-refresh'

function loginOnline() {
  useAuthStore.getState().initSession(
    { id: 'u1', email: EMAIL, first_name: 'Ada', last_name: 'O', phone: '', is_verified: true } as any,
    { access: 'a.b.c', refresh: 'refresh-token-v1' } as any,
    ORG as any,
    [ORG] as any,
  )
}

function startGraceSession() {
  const blob = {
    algorithm: 'pbkdf2_sha256', iterations: 600_000, salt: 'c2FsdA==', hash: 'aGFzaA==',
    user_id: 'u1', email: EMAIL, mfa_enabled: false, token_version: 1,
    issued_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 14 * 86400_000).toISOString(),
    organisations: [{ ...ORG, is_active: true, onboarding_completed: true }],
  } as unknown as OfflineVerifierBlob
  useAuthStore.getState().startOfflineSession(blob)
}

// clearSession drops the in-memory resume secrets through a dynamic import
// (a microtask) — a macrotask tick makes tests deterministic about it.
async function clearSessionSettled() {
  useAuthStore.getState().clearSession()
  await new Promise((r) => setTimeout(r, 0))
}

beforeEach(async () => {
  postMock.mockReset()
  localStorage.clear()
  await deleteStoredRefresh() // also clears in-memory secrets
  await clearSessionSettled()
})

describe('stash → unlock → silent resume', () => {
  it('upgrades an offline grace session in place, with no re-login', async () => {
    // Online login stashes the wrapped refresh token
    loginOnline()
    await stashRefreshAtLogin(EMAIL, PASSWORD)
    const stashedBlob = localStorage.getItem(REFRESH_KEY)
    expect(stashedBlob).toBeTruthy()
    expect(stashedBlob).not.toContain('refresh-token-v1') // never plaintext on disk

    // App restart: session gone, memory secrets gone, disk blob survives
    await clearSessionSettled()
    expect(localStorage.getItem(REFRESH_KEY)).toBe(stashedBlob)

    // Offline unlock: the typed password unwraps the token into memory
    expect(await unlockRefreshOffline(EMAIL, PASSWORD)).toBe(true)
    startGraceSession()
    expect(useAuthStore.getState().tokens).toBeNull()

    // Connectivity returns → silent resume
    postMock.mockResolvedValue({ data: { access: 'new.access.jwt', refresh: 'refresh-token-v2' } })
    const resumed = await trySilentResume()

    expect(resumed).toBe(true)
    expect(postMock).toHaveBeenCalledWith('/auth/token/refresh/', { refresh: 'refresh-token-v1' })
    const s = useAuthStore.getState()
    expect(s.isOfflineSession).toBe(false)          // real session now
    expect(s.tokens?.access).toBe('new.access.jwt')
    expect(s.tokens?.refresh).toBe('refresh-token-v2')
    expect(s.isAuthenticated).toBe(true)
    expect(s.organisation?.id).toBe(ORG.id)         // org context preserved

    // The rotated token was re-wrapped on disk (old one is blacklisted)
    await vi.waitFor(() => {
      expect(localStorage.getItem(REFRESH_KEY)).not.toBe(stashedBlob)
    })

    // Unlocking the NEW blob yields the rotated token
    clearResumeMemory()
    expect(await unlockRefreshOffline(EMAIL, PASSWORD)).toBe(true)
    postMock.mockClear()
    startGraceSession()
    postMock.mockResolvedValue({ data: { access: 'x.y.z', refresh: 'refresh-token-v3' } })
    await trySilentResume()
    expect(postMock).toHaveBeenCalledWith('/auth/token/refresh/', { refresh: 'refresh-token-v2' })
  })

  it('rejects the wrong password (AES-GCM auth) and leaves nothing usable in memory', async () => {
    loginOnline()
    await stashRefreshAtLogin(EMAIL, PASSWORD)
    clearResumeMemory()

    expect(await unlockRefreshOffline(EMAIL, 'WrongPassword1!')).toBe(false)
    expect(await unlockRefreshOffline('other@example.com', PASSWORD)).toBe(false)

    // Failed unlock ⇒ no resume possible
    startGraceSession()
    expect(await trySilentResume()).toBe(false)
    expect(postMock).not.toHaveBeenCalled()
  })

  it('cannot resume without a prior unlock — clearSession drops memory secrets', async () => {
    loginOnline()
    await stashRefreshAtLogin(EMAIL, PASSWORD)

    // Session torn down (startup guard / inactivity / expiry)
    await clearSessionSettled()
    startGraceSession()

    // Disk blob exists, but nothing was unlocked this session → banner path
    expect(localStorage.getItem(REFRESH_KEY)).toBeTruthy()
    expect(await trySilentResume()).toBe(false)
    expect(postMock).not.toHaveBeenCalled()
  })

  it('deletes a dead token on 401 (expired / blacklisted / password changed) and falls back', async () => {
    loginOnline()
    await stashRefreshAtLogin(EMAIL, PASSWORD)
    await clearSessionSettled()
    await unlockRefreshOffline(EMAIL, PASSWORD)
    startGraceSession()

    postMock.mockRejectedValue({ response: { status: 401 } })
    expect(await trySilentResume()).toBe(false)

    // Blob removed so every future reconnect doesn't retry a dead token
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
    // Still a grace session — the banner flow takes over
    expect(useAuthStore.getState().isOfflineSession).toBe(true)

    // A transient NETWORK failure must NOT delete the blob
    localStorage.setItem(REFRESH_KEY, '{"v":1}')
    postMock.mockRejectedValue(new Error('Network Error'))
    expect(await trySilentResume()).toBe(false)
    expect(localStorage.getItem(REFRESH_KEY)).toBeTruthy()
  })

  it('destroying the verifier destroys the wrapped refresh token with it', async () => {
    loginOnline()
    await stashRefreshAtLogin(EMAIL, PASSWORD)
    expect(localStorage.getItem(REFRESH_KEY)).toBeTruthy()

    await deleteVerifier() // logout / 5 failed attempts / server-side revocation
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
  })
})
