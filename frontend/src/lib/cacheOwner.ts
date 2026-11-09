/**
 * Remembers which user the offline cache belongs to.
 *
 * The offline cache is keyed by organisation + URL, not by user. On a shared
 * machine a second person signing in to the same business would otherwise see
 * the first person's name, avatar and role-based menu from cached responses.
 * When the signed-in user is not the one who filled the cache, we wipe it.
 */
const KEY = 'audity:cache-owner-user-id'

/** Pure decision, exported for tests. */
export function shouldClearCache(previous: string | null, current: string, online: boolean): boolean {
  if (previous === current) return false
  // Unknown owner (first run after this fix): only clear when online, so a
  // returning user who is offline keeps their saved data.
  if (previous === null) return online
  return true
}

/** Call whenever a user is signed in. Clears the cache if the user changed. */
export function claimCacheForUser(userId: string | undefined | null): void {
  if (!userId) return
  let previous: string | null = null
  try { previous = localStorage.getItem(KEY) } catch { /* storage unavailable */ }
  const online = typeof navigator === 'undefined' ? true : navigator.onLine !== false
  const clear = shouldClearCache(previous, userId, online)
  // Offline with an unknown owner: leave it unset so the next online sign-in decides.
  if (previous !== userId && !(previous === null && !online)) {
    try { localStorage.setItem(KEY, userId) } catch { /* ignore */ }
  }
  if (clear) {
    import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()).catch(() => {})
  }
}
