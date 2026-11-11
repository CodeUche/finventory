/**
 * Per-user data kept in localStorage that another person in the same business
 * must not see: the profile picture inside the saved media, and held baskets.
 *
 * Held baskets are keyed by organisation AND user, so the same person signing
 * back in gets their own baskets back and nobody else ever sees them. When a
 * different user signs in, the old user's baskets are deleted.
 */

const HELD_PREFIXES = ['audity-held-baskets-', 'audity-register-held-']
const MEDIA_PREFIX = 'audity-media'
const LEGACY_QUEUE_KEY = 'finventory_offline_queue'

export const heldBasketsKey = (orgId: string | null | undefined, userId: string | null | undefined) =>
  `audity-held-baskets-${orgId ?? 'none'}:${userId ?? 'none'}`
export const registerHeldKey = (orgId: string | null | undefined, userId: string | null | undefined) =>
  `audity-register-held-${orgId ?? 'none'}:${userId ?? 'none'}`

function allKeys(): string[] {
  const keys: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k) keys.push(k)
    }
  } catch { /* storage unavailable */ }
  return keys
}

/** Remove the profile picture from every saved media entry. Logo and stamp are business assets and stay. */
export function clearSavedAvatars(): void {
  for (const k of allKeys()) {
    if (k !== MEDIA_PREFIX && !k.startsWith(`${MEDIA_PREFIX}:`)) continue
    try {
      const raw = localStorage.getItem(k)
      if (!raw) continue
      const obj = JSON.parse(raw) as Record<string, unknown>
      if (obj && typeof obj === 'object' && 'avatarDataUrl' in obj) {
        delete obj.avatarDataUrl
        localStorage.setItem(k, JSON.stringify(obj))
      }
    } catch { /* unreadable entry: leave it */ }
  }
}

/**
 * Delete held baskets that do not belong to `keepUserId`. Old-format keys
 * (no user part) belong to nobody we can identify and are always deleted.
 */
export function clearHeldBasketsExcept(keepUserId: string | null | undefined): void {
  for (const k of allKeys()) {
    if (!HELD_PREFIXES.some((p) => k.startsWith(p))) continue
    const owner = k.includes(':') ? k.slice(k.lastIndexOf(':') + 1) : null
    if (keepUserId && owner === keepUserId) continue
    try { localStorage.removeItem(k) } catch { /* ignore */ }
  }
}

/** The retired localStorage queue (no longer used). Remove anything left behind. */
export function clearLegacyQueue(): void {
  try { localStorage.removeItem(LEGACY_QUEUE_KEY) } catch { /* ignore */ }
}
