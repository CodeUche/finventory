/**
 * Guard for the saved copies of business data on this device (the response
 * cache and the local entity store).
 *
 * Three jobs:
 *  1. Wipe them, and REMEMBER that a wipe is owed until both deletes really
 *     succeeded (a "wipe pending" mark in localStorage). A wipe that fails, is
 *     blocked by another tab, or is cut short by the app closing is retried at
 *     the next start-up and the next sign-in.
 *  2. Make readers wait for a wipe that is running, and see nothing while one
 *     is still owed, so the next person can never read the last person's data.
 *  3. Keep a "session generation" number. It goes up whenever the signed-in
 *     user is wiped or changes. A request that started under an older number
 *     must not write its answer into the saved copies.
 *
 * This file must not import the auth store or the data stores at the top
 * (they import this file); it loads them on demand.
 */

const PENDING_KEY = 'audity:wipe-pending'

let generation = 0
let pendingInMemory = false
let inProgress: Promise<boolean> | null = null

/** Number that changes whenever saved data is wiped or the user changes. */
export function getGeneration(): number { return generation }
export function bumpGeneration(): void { generation++ }

/** True while a wipe is owed (not yet fully done). Works without localStorage. */
export function isWipePending(): boolean {
  if (pendingInMemory) return true
  try { return localStorage.getItem(PENDING_KEY) === '1' } catch { return false }
}

function setPending(on: boolean): void {
  pendingInMemory = on
  try {
    if (on) localStorage.setItem(PENDING_KEY, '1')
    else localStorage.removeItem(PENDING_KEY)
  } catch { /* storage unavailable: the in-memory mark still protects this run */ }
}

/** Resolves once any running wipe has finished. Never rejects. */
export async function waitForWipe(): Promise<void> {
  if (inProgress) await inProgress.catch(() => false)
}

/**
 * Readers call this first. Waits for a running wipe, then says whether the
 * saved copies may be read. False means "act as if nothing is saved".
 */
export async function canReadSavedData(): Promise<boolean> {
  await waitForWipe()
  return !isWipePending()
}

/**
 * Writers call this. False when saved data must not be written: a wipe is
 * owed, or the user changed since `startedAt` (a number from getGeneration()
 * taken when the work began).
 */
export function canWriteSavedData(startedAt?: number): boolean {
  if (isWipePending()) return false
  return startedAt === undefined || startedAt === generation
}

/**
 * Delete a whole IndexedDB database by name. Resolves true when it is gone (or
 * there is no IndexedDB at all, so nothing can be stored), false when it
 * failed or stayed blocked. Used only when clearing a store fails.
 */
export function deleteDatabaseByName(name: string): Promise<boolean> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') { resolve(true); return }
      const req = indexedDB.deleteDatabase(name)
      const timer = setTimeout(() => resolve(false), 3000)
      req.onsuccess = () => { clearTimeout(timer); resolve(true) }
      req.onerror = () => { clearTimeout(timer); resolve(false) }
      req.onblocked = () => { /* wait: it finishes when the other tab lets go, or the timer gives up */ }
    } catch { resolve(false) }
  })
}

async function doWipe(): Promise<boolean> {
  const results = await Promise.all([
    import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()).catch(() => false),
    import('@/lib/localStore').then(({ localStore }) => localStore.clearAll()).catch(() => false),
  ])
  return results.every((r) => r === true)
}

/**
 * Wipe the saved copies of business data. Synchronously marks the wipe as owed
 * and raises the generation, so anything that runs after this call already
 * sees "nothing readable" and "no writes". Resolves true only when BOTH
 * deletes succeeded; only then is the owed mark removed. Never rejects.
 */
export function startWipe(): Promise<boolean> {
  bumpGeneration()
  setPending(true)
  const previous = inProgress ?? Promise.resolve(true)
  const run: Promise<boolean> = previous
    .then(() => doWipe())
    .catch(() => false)
    .then((ok) => {
      // Only the newest wipe may clear the owed mark; an older one finishing
      // while a newer one is queued must not let readers back in early.
      if (ok && inProgress === run) setPending(false)
      return ok
    })
  inProgress = run
  void run.then(() => { if (inProgress === run) inProgress = null })
  return run
}

/** If a wipe is still owed (from an earlier failure or a killed app), do it now. */
export function retryPendingWipe(): Promise<boolean> {
  return isWipePending() ? startWipe() : Promise.resolve(true)
}
