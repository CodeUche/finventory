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

/**
 * Wipe everything the app keeps on disk as a READ copy of business data:
 * the response cache AND the local entity store (customers, invoices, payroll,
 * ...). Waits for both deletes. Never throws, even if IndexedDB is unavailable.
 *
 * Deliberately NOT touched: the sync queue (a user's unsent offline work; it is
 * tagged with its owner and hidden from everyone else, see syncEngine) and the
 * offline sign-in verifier.
 */
export async function clearLocalReadData(): Promise<void> {
  const wipes: Array<Promise<unknown>> = [
    import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()),
    import('@/lib/localStore').then(({ localStore }) => localStore.clearAll()),
  ]
  await Promise.allSettled(wipes)
}

/**
 * Call whenever a user is signed in. Clears the saved copies of business data
 * if the user changed. Returns a promise that settles when the wipe is done;
 * callers may ignore it.
 */
export function claimCacheForUser(userId: string | undefined | null): Promise<void> {
  if (!userId) return Promise.resolve()
  let previous: string | null = null
  try { previous = localStorage.getItem(KEY) } catch { /* storage unavailable */ }
  const online = typeof navigator === 'undefined' ? true : navigator.onLine !== false
  const clear = shouldClearCache(previous, userId, online)
  // Offline with an unknown owner: leave it unset so the next online sign-in decides.
  if (previous !== userId && !(previous === null && !online)) {
    try { localStorage.setItem(KEY, userId) } catch { /* ignore */ }
  }
  const work: Array<Promise<unknown>> = []
  if (previous !== userId) {
    // Unsent offline changes made before owners were recorded belong to the
    // previous user if we know them, otherwise to whoever is signing in now.
    work.push(
      import('@/lib/syncEngine')
        .then(({ syncEngine }) => syncEngine.adoptUnownedItems(previous ?? userId))
        .catch(() => {}),
    )
  }
  if (clear) work.push(clearLocalReadData())
  return Promise.all(work).then(() => {})
}
