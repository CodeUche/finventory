/**
 * Offline re-authentication via PBKDF2-HMAC-SHA256 (600k iterations, WebCrypto).
 *
 * Security model
 * ──────────────
 * After a successful online login the server issues a one-time PBKDF2 verifier
 * blob (salt + hash; the server keeps no copy).  We AES-256-GCM encrypt it before
 * writing to localStorage so the raw hash is never stored in plain text.  The
 * wrapper key lives in a separate localStorage slot — both pieces are required to
 * reconstruct the verifier.
 *
 * After MAX_ATTEMPTS failed attempts the local verifier is wiped; the user must
 * perform an online login to re-issue it.
 *
 * Note: this is NOT equivalent to OS-keychain storage (which would require
 * @tauri-apps/plugin-stronghold, not yet installed).  It prevents casual
 * file-system reads and casual localStorage sniffing, which is the realistic
 * threat model for a desktop accounting app.
 */

import type { Organisation } from '@/types'

const ENCRYPTED_BLOB_KEY = 'audity-offline-verifier'
const WRAPPER_KEY_SLOT   = 'audity-offline-key'
const ATTEMPTS_KEY       = 'audity-offline-attempts'
const MAX_ATTEMPTS       = 5

// ── Types ──────────────────────────────────────────────────────────────────

export interface OfflineVerifierBlob {
  algorithm: 'pbkdf2_sha256'
  iterations: number
  salt: string          // base64-encoded 16 bytes
  hash: string          // base64-encoded 32 bytes
  user_id: string
  email: string
  // Identity snapshot — lets the offline sidebar / permission gates work with
  // no network. Without is_superuser here, a superuser's offline (or silently
  // resumed) session is treated as a permission-less sub-account.
  first_name?: string
  last_name?: string
  phone?: string
  is_superuser?: boolean
  is_staff?: boolean
  is_sub_account?: boolean
  has_partner_profile?: boolean
  mfa_enabled: boolean
  token_version: number
  issued_at: string
  expires_at: string
  organisations: Array<Pick<Organisation, 'id' | 'name' | 'slug' | 'account_type' | 'currency' | 'country'> & {
    is_active: boolean
    onboarding_completed: boolean
    // Per-org RBAC + plan snapshot (present on blobs issued after the
    // identity-snapshot change; older blobs omit them → sidebar falls back to
    // its online fetch on reconnect).
    role?: string | null
    module_permissions?: Array<{ module: string; access_level: string }>
    plan_modules?: string[] | null
    plan_tax_engine?: string | null
    plan_name?: string | null
    subscription_expired?: boolean
  }>
}

// ── AES-256-GCM helpers ────────────────────────────────────────────────────

async function getOrCreateWrapperKey(): Promise<CryptoKey> {
  const stored = localStorage.getItem(WRAPPER_KEY_SLOT)
  if (stored) {
    try {
      return await crypto.subtle.importKey(
        'jwk', JSON.parse(stored), { name: 'AES-GCM' }, false, ['encrypt', 'decrypt'],
      )
    } catch { /* corrupted — fall through and generate */ }
  }
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt'])
  const jwk = await crypto.subtle.exportKey('jwk', key)
  localStorage.setItem(WRAPPER_KEY_SLOT, JSON.stringify(jwk))
  return key
}

async function encryptBlob(plaintext: string): Promise<string> {
  const key = await getOrCreateWrapperKey()
  const iv  = crypto.getRandomValues(new Uint8Array(12))
  const ct  = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(plaintext))
  const out = new Uint8Array(12 + ct.byteLength)
  out.set(iv)
  out.set(new Uint8Array(ct), 12)
  return btoa(String.fromCharCode(...out))
}

async function decryptBlob(b64: string): Promise<string> {
  const key = await getOrCreateWrapperKey()
  const buf = Uint8Array.from(atob(b64), c => c.charCodeAt(0))
  const pt  = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: buf.slice(0, 12) }, key, buf.slice(12))
  return new TextDecoder().decode(pt)
}

// ── Attempt counter ────────────────────────────────────────────────────────

interface AttemptRecord { email: string; count: number }

function readAttempts(): AttemptRecord | null {
  try { return JSON.parse(localStorage.getItem(ATTEMPTS_KEY) ?? 'null') } catch { return null }
}
function writeAttempts(r: AttemptRecord) {
  localStorage.setItem(ATTEMPTS_KEY, JSON.stringify(r))
}
function clearAttempts() {
  localStorage.removeItem(ATTEMPTS_KEY)
}

export function getRemainingAttempts(email: string): number {
  const r = readAttempts()
  if (!r || r.email !== email) return MAX_ATTEMPTS
  return Math.max(0, MAX_ATTEMPTS - r.count)
}

// ── Verifier storage ───────────────────────────────────────────────────────

export async function storeVerifier(blob: OfflineVerifierBlob): Promise<void> {
  const enc = await encryptBlob(JSON.stringify(blob))
  localStorage.setItem(ENCRYPTED_BLOB_KEY, enc)
  clearAttempts()
}

export async function loadVerifier(email: string): Promise<OfflineVerifierBlob | null> {
  const enc = localStorage.getItem(ENCRYPTED_BLOB_KEY)
  if (!enc) return null
  try {
    const json = await decryptBlob(enc)
    const blob: OfflineVerifierBlob = JSON.parse(json)
    return blob.email === email ? blob : null
  } catch {
    return null
  }
}

/** True if any verifier blob exists (email-agnostic, synchronous). */
export function hasVerifierStored(): boolean {
  return !!localStorage.getItem(ENCRYPTED_BLOB_KEY)
}

export function isVerifierExpired(blob: OfflineVerifierBlob): boolean {
  return new Date(blob.expires_at) <= new Date()
}

export async function deleteVerifier(): Promise<void> {
  localStorage.removeItem(ENCRYPTED_BLOB_KEY)
  // The password-wrapped refresh token (offlineResume.ts) is only reachable
  // through the same unlock path — whenever the verifier is destroyed
  // (logout, attempt exhaustion, server-side revocation), it goes too.
  localStorage.removeItem('audity-offline-refresh')
  clearAttempts()
}

// ── PBKDF2 derivation + constant-time compare ──────────────────────────────

async function deriveKey(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  const km = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits'])
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: salt as Uint8Array<ArrayBuffer>, iterations }, km, 256)
  return new Uint8Array(bits)
}

function constantTimeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i]
  return diff === 0
}

// ── Main entry point ───────────────────────────────────────────────────────

export type OfflineLoginResult =
  | { ok: true; blob: OfflineVerifierBlob }
  | { ok: false; reason: 'no_verifier' | 'expired' | 'too_many_attempts' | 'wrong_password'; remaining?: number }

/**
 * Attempt offline login.  ~0.5 s at 600k PBKDF2 iterations.
 * Returns `ok: true` with the verifier blob on success.
 * On wrong password, increments the attempt counter and returns remaining tries.
 * After MAX_ATTEMPTS the local verifier is wiped and `too_many_attempts` is returned.
 */
export async function tryOfflineLogin(email: string, password: string): Promise<OfflineLoginResult> {
  const blob = await loadVerifier(email)
  if (!blob) return { ok: false, reason: 'no_verifier' }

  if (isVerifierExpired(blob)) {
    await deleteVerifier()
    return { ok: false, reason: 'expired' }
  }

  const remaining = getRemainingAttempts(email)
  if (remaining <= 0) {
    await deleteVerifier()
    return { ok: false, reason: 'too_many_attempts' }
  }

  const saltBytes = new Uint8Array(Array.from(atob(blob.salt), c => c.charCodeAt(0)))
  const hashBytes = new Uint8Array(Array.from(atob(blob.hash), c => c.charCodeAt(0)))
  const derived   = await deriveKey(password, saltBytes, blob.iterations)
  const match     = constantTimeEqual(derived, hashBytes)

  if (!match) {
    const rec      = readAttempts()
    const newCount = (rec?.email === email ? rec.count : 0) + 1
    const newLeft  = MAX_ATTEMPTS - newCount
    if (newLeft <= 0) {
      await deleteVerifier()
      clearAttempts()
      return { ok: false, reason: 'too_many_attempts' }
    }
    writeAttempts({ email, count: newCount })
    return { ok: false, reason: 'wrong_password', remaining: newLeft }
  }

  clearAttempts()
  return { ok: true, blob }
}
