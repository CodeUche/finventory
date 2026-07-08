/**
 * Silent session resume — password-wrapped refresh token.
 *
 * Closes the last UX seam in offline-first: a session that STARTED with the
 * offline password unlock has no server credential, so when connectivity
 * returns the user used to be asked to sign in again before their queued
 * work could sync. With this module, the refresh token is stored on disk
 * encrypted under a key derived from the USER'S PASSWORD — so:
 *
 *   • Online login  → refresh token wrapped + stored (fire-and-forget).
 *   • Offline unlock → the same password the user just typed also unwraps
 *     the refresh token into memory (never onto disk in plain form).
 *   • Connectivity returns → trade the refresh token for fresh JWTs and
 *     upgrade the grace session IN PLACE: no banner, no re-login, queue
 *     flushes silently. The trader never stops selling.
 *
 * Security model
 * ──────────────
 *   • The wrap key is derived with PBKDF2-HMAC-SHA256 (600k iterations)
 *     from the password using a salt INDEPENDENT of the offline verifier's
 *     salt. This matters: the verifier blob stores PBKDF2(password, salt_v)
 *     itself, so reusing salt_v would make the stored hash the decryption
 *     key. A fresh salt keeps "can read the disk" ≠ "can decrypt".
 *   • Nothing here weakens the at-rest posture: with or without this file,
 *     the only attack is brute-forcing the password — and a cracked
 *     password is already a full, non-expiring server credential.
 *   • BLACKLIST_AFTER_ROTATION=True server-side: every token refresh kills
 *     the previous refresh token, so api.ts calls onTokensRotated() after
 *     each rotation and we re-wrap the new one with the in-memory key.
 *   • Password change on any device bumps token_version, which the backend
 *     enforces on every request — a stale wrapped token then fails resume
 *     (401) and is deleted; the visible-banner flow takes over.
 *   • clearSession (startup guard / expiry / inactivity) wipes the
 *     IN-MEMORY secrets only — re-entering the password re-unlocks them.
 *     logout / verifier wipe removes the blob from disk entirely.
 */

import { useAuthStore } from '@/store/authStore'

const STORAGE_KEY = 'audity-offline-refresh'
const PBKDF2_ITERATIONS = 600_000

interface WrappedRefresh {
  v: 1
  email: string
  salt: string       // base64, 16 bytes — independent of the verifier salt
  payload: string    // base64: 12-byte IV ‖ AES-256-GCM ciphertext of the refresh token
  issued_at: string
}

// In-memory session secrets. Never persisted; die with the process and are
// explicitly cleared on clearSession/logout.
let _wrapKey: CryptoKey | null = null
let _refreshToken: string | null = null
let _resuming = false

// ── Crypto helpers ───────────────────────────────────────────────────────────

function b64encode(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
}
function b64decode(s: string): Uint8Array {
  return new Uint8Array(Array.from(atob(s), (c) => c.charCodeAt(0)))
}

async function deriveWrapKey(password: string, salt: Uint8Array): Promise<CryptoKey> {
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: salt as Uint8Array<ArrayBuffer>, iterations: PBKDF2_ITERATIONS },
    km,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

async function encryptToken(key: CryptoKey, token: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(token))
  const out = new Uint8Array(12 + ct.byteLength)
  out.set(iv)
  out.set(new Uint8Array(ct), 12)
  return b64encode(out)
}

async function decryptToken(key: CryptoKey, payload: string): Promise<string> {
  const buf = b64decode(payload)
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf.slice(0, 12) }, key, buf.slice(12))
  return new TextDecoder().decode(pt)
}

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Wrap the current session's refresh token under the password and store it.
 * Call fire-and-forget right after a successful ONLINE login (the only
 * moment the plaintext password exists). ~0.5 s of PBKDF2 in the background.
 */
export async function stashRefreshAtLogin(email: string, password: string): Promise<void> {
  const refresh = useAuthStore.getState().tokens?.refresh
  if (!refresh) return
  const salt = crypto.getRandomValues(new Uint8Array(16))
  const key = await deriveWrapKey(password, salt)
  const payload = await encryptToken(key, refresh)
  const blob: WrappedRefresh = { v: 1, email, salt: b64encode(salt), payload, issued_at: new Date().toISOString() }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(blob))
  _wrapKey = key
  _refreshToken = refresh
}

/**
 * During offline unlock: use the just-typed (and just-verified) password to
 * decrypt the stored refresh token into memory. Non-fatal — returns false
 * when nothing is stored, the email doesn't match, or decryption fails.
 */
export async function unlockRefreshOffline(email: string, password: string): Promise<boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return false
    const blob: WrappedRefresh = JSON.parse(raw)
    if (blob.email !== email) return false
    const key = await deriveWrapKey(password, b64decode(blob.salt))
    _refreshToken = await decryptToken(key, blob.payload) // GCM auth throws on wrong password/tamper
    _wrapKey = key
    return true
  } catch {
    return false
  }
}

/**
 * Re-wrap after a server-side token rotation (BLACKLIST_AFTER_ROTATION means
 * the previously stored token just died). No-op when no wrap key is in
 * memory — a later resume then falls back to the sign-in banner.
 */
export function onTokensRotated(newRefresh: string): void {
  if (!_wrapKey || !newRefresh) return
  const key = _wrapKey
  _refreshToken = newRefresh
  void (async () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw) return
      const blob: WrappedRefresh = JSON.parse(raw)
      blob.payload = await encryptToken(key, newRefresh)
      blob.issued_at = new Date().toISOString()
      localStorage.setItem(STORAGE_KEY, JSON.stringify(blob))
    } catch { /* non-fatal — worst case the banner flow takes over */ }
  })()
}

/**
 * Upgrade an offline grace session to a real-token session in place, without
 * any user interaction. Returns true on success (caller then flushes the
 * sync queue); false means "show the sign-in banner instead".
 */
export async function trySilentResume(): Promise<boolean> {
  const s = useAuthStore.getState()
  if (!s.isAuthenticated || !s.isOfflineSession || !s.user) return false
  if (!_refreshToken || _resuming) return false
  const currentRefresh = _refreshToken
  _resuming = true
  try {
    const { api } = await import('@/services/api')
    const { data } = await api.post('/auth/token/refresh/', { refresh: currentRefresh })
    if (!data?.access) return false
    const rotated: string = data.refresh ?? currentRefresh
    onTokensRotated(rotated)
    // Commit a real session first (flips isOfflineSession→false and lands the
    // tokens, so the profile GET below leaves offline/cache mode). The org
    // context comes from the verifier snapshot; the synthetic user already
    // carries is_superuser etc. from the blob, so the sidebar is correct even
    // if the profile fetch below fails.
    s.initSession(s.user, { access: data.access, refresh: rotated }, s.organisation, s.organisations)
    // Backfill the authoritative user profile (avatar, exact names, and any
    // identity flags that changed since the verifier was issued). Non-fatal.
    try {
      const { authApi } = await import('@/services/api')
      const { data: profile } = await authApi.profile()
      if (profile && typeof profile === 'object') {
        useAuthStore.getState().updateUser(profile)
      }
    } catch { /* non-fatal — blob identity + AppLayout refresh still apply */ }
    // AppLayout re-fetches org, membership, and plan from the network.
    window.dispatchEvent(new CustomEvent('audity:app-refresh'))
    return true
  } catch (err) {
    // Expired / blacklisted / token_version bumped by a password change:
    // the stored token is permanently dead — remove it so we don't retry
    // on every reconnect. Network failures keep it for the next attempt.
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 400 || status === 401) await deleteStoredRefresh()
    return false
  } finally {
    _resuming = false
  }
}

/** Drop the in-memory secrets (session ended); the disk blob survives. */
export function clearResumeMemory(): void {
  _wrapKey = null
  _refreshToken = null
}

/** Full wipe: disk blob + memory. Used by logout and verifier destruction. */
export async function deleteStoredRefresh(): Promise<void> {
  localStorage.removeItem(STORAGE_KEY)
  clearResumeMemory()
}
