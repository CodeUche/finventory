/**
 * Remembers which user the offline cache belongs to.
 *
 * The offline cache is keyed by organisation + URL, not by user. On a shared
 * machine a second person signing in to the same business would otherwise see
 * the first person's name, avatar and role-based menu from cached responses.
 * When the signed-in user is not the one who filled the cache, we wipe it.
 */
import { startWipe, bumpGeneration, isWipePending, reportWipeFailure } from '@/lib/localDataGuard'
import { tagUntaggedAvatars, clearAvatarsExcept, clearHeldBasketsExcept } from '@/lib/localUserData'

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
 * Wipe the saved copies of business data: the response cache AND the local
 * entity store. Marks the wipe as owed first, resolves true only when both
 * deletes really succeeded, and never throws. See localDataGuard.
 *
 * Deliberately NOT touched: the sync queue (a user's unsent offline work; each
 * item is tagged with its owner and hidden from everyone else, see syncEngine)
 * and the offline sign-in verifier.
 */
export function clearLocalReadData(): Promise<boolean> {
  return startWipe()
}

/**
 * Old unsent changes with no owner go to the previous user. If that is unknown
 * we ask the offline verifier who it belongs to. If that is unknown too, they
 * stay hidden from everyone: it is better to strand them than to hand one
 * person's unsent work to another.
 */
async function adoptOwnerlessQueueItems(previous: string | null): Promise<void> {
  try {
    let owner = previous
    if (!owner) {
      const { peekVerifierUserId } = await import('@/lib/offlineVerifier')
      owner = await peekVerifierUserId()
    }
    if (!owner) return
    const { syncEngine } = await import('@/lib/syncEngine')
    await syncEngine.adoptUnownedItems(owner)
  } catch { /* adoption failed: the items stay hidden */ }
}

/**
 * Call whenever a user is signed in. Clears the saved copies of business data
 * if the user changed. The wipe is marked as owed BEFORE this returns, so any
 * read that follows already waits for it. The returned promise settles when
 * everything is done; callers may ignore it.
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
  if (previous !== userId) bumpGeneration()
  // A picture saved before owners were recorded is the previous owner's, if we know them.
  if (previous) tagUntaggedAvatars(previous)
  if (clear) {
    work.push(startWipe().then((ok) => { if (!ok) reportWipeFailure() }))
    // Other people's per-user leftovers go too (profile picture, held baskets).
    clearAvatarsExcept(userId)
    clearHeldBasketsExcept(userId)
  } else if (isWipePending()) {
    // An earlier wipe failed or was cut short: finish it before anything is read.
    work.push(startWipe())
  }
  work.push(adoptOwnerlessQueueItems(previous))
  return Promise.all(work).then(() => {})
}
