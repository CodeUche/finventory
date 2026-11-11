/**
 * Per-user data kept in localStorage that another person in the same business
 * must not see: the profile picture inside the saved media, and held baskets.
 * The picture is tagged with its owner: kept for that user across sign-outs,
 * never shown to anyone else, deleted when a different user signs in.
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

function mediaKeys(): string[] {
  return allKeys().filter((k) => k === MEDIA_PREFIX || k.startsWith(`${MEDIA_PREFIX}:`))
}

/** Read, change and save every saved media entry. Unreadable entries are left alone. */
function editMedia(change: (obj: Record<string, unknown>) => boolean): void {
  for (const k of mediaKeys()) {
    try {
      const raw = localStorage.getItem(k)
      if (!raw) continue
      const obj = JSON.parse(raw) as Record<string, unknown>
      if (obj && typeof obj === 'object' && change(obj)) localStorage.setItem(k, JSON.stringify(obj))
    } catch { /* unreadable entry: leave it */ }
  }
}

/**
 * Give profile pictures saved before owners were recorded to `ownerId`
 * (the previous cache owner). Call with an owner only when it is known.
 */
export function tagUntaggedAvatars(ownerId: string): void {
  editMedia((obj) => {
    if (!obj.avatarDataUrl || obj.avatarOwnerId) return false
    obj.avatarOwnerId = ownerId
    return true
  })
}

/**
 * Delete every profile picture that does not belong to `keepUserId` (including
 * pictures with no owner). Logo and stamp are business assets and stay.
 */
export function clearAvatarsExcept(keepUserId: string | null | undefined): void {
  editMedia((obj) => {
    if (!('avatarDataUrl' in obj) && !('avatarOwnerId' in obj)) return false
    if (keepUserId && obj.avatarOwnerId === keepUserId) return false
    delete obj.avatarDataUrl
    delete obj.avatarOwnerId
    return true
  })
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
