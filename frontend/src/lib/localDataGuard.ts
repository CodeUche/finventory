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

/**
 * Time limits (ms). Every wait in here is bounded so a database that hangs
 * (held open by another tab, a stalled open) can never freeze the app.
 * Mutable only so tests can shorten them.
 */
export const wipeTimeouts = { read: 3000, step: 3000 }

/** Resolve with `fallback` if `p` has not settled within `ms`. Never rejects. */
export function withTimeout<T>(p: Promise<T>, ms: number, fallback: T): Promise<T> {
  return new Promise<T>((resolve) => {
    const timer = setTimeout(() => resolve(fallback), ms)
    p.then(
      (v) => { clearTimeout(timer); resolve(v) },
      () => { clearTimeout(timer); resolve(fallback) },
    )
  })
}

/**
 * Who is signed in right now. The auth store registers the real answer; until
 * it does (unit tests of single files) everything is allowed.
 */
export interface SessionInfo { signedIn: boolean; userId: string | null; orgId: string | null }
let probe: () => SessionInfo = () => ({ signedIn: true, userId: null, orgId: null })
export function setSessionProbe(fn: () => SessionInfo): void { probe = fn }
export function getSessionInfo(): SessionInfo { return probe() }

/**
 * True while the person who asked is still the signed-in user. Slow answers
 * (membership, plan, organisation list) must check this before applying
 * themselves to the app state.
 */
export function stillSignedInAs(userId: string | null | undefined): boolean {
  const s = probe()
  return !!userId && s.signedIn && s.userId === userId
}

/** Org values that mean "no business is selected": nothing may be saved under them. */
const NO_ORG = new Set(['', 'anonymous', 'unknown', 'none'])

/**
 * Identity and sign-in endpoints (who the user is, tokens) must never be saved
 * or served from the saved copies: a cached answer could show the wrong person.
 */
export function isIdentityUrl(url: string): boolean {
  return url.includes('/auth/')
}

/**
 * Saved data is scoped to the business AND the user. Another user can never
 * read an entry, even if a wipe failed or never ran.
 */
export function savedScope(orgId: string): string {
  return `${orgId}~${probe().userId ?? 'nouser'}`
}

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

/**
 * Resolves once any running wipe has finished, or after a short limit. Never
 * rejects. On a timeout the owed mark is still set, so readers see "nothing"
 * rather than waiting for a stuck database.
 */
export async function waitForWipe(): Promise<void> {
  if (inProgress) await withTimeout(inProgress, wipeTimeouts.read, false)
  if (legacyMigration) await withTimeout(legacyMigration, wipeTimeouts.read, false)
}

// ── One-time cleanup of saved entries written before entries were user-scoped ──
const MIGRATED_KEY = 'audity:saved-scope-v2'
const OWNER_KEY = 'audity:cache-owner-user-id'
let legacyMigration: Promise<boolean> | null = null
let legacyJob: { cancelled: boolean } | null = null

/**
 * Entries saved by older builds are keyed by business only, so they cannot be
 * tied to a user. If the recorded cache owner is known they are re-keyed to
 * that owner (an upgrading offline user keeps their data); otherwise they are
 * deleted. They are never given to anyone but the recorded owner. Runs once.
 * Readers wait for it (briefly) so nothing reads half-converted data.
 */
export function migrateLegacySavedData(): Promise<boolean> {
  let done = false
  try { done = localStorage.getItem(MIGRATED_KEY) === '1' } catch { /* storage unavailable */ }
  if (done) return Promise.resolve(true)
  let owner: string | null = null
  try { owner = localStorage.getItem(OWNER_KEY) } catch { /* unknown owner: delete */ }
  // A wipe that is owed means the owner marker cannot be trusted (it can be set
  // while the wipe never happened). Delete the old entries instead of re-keying.
  if (isWipePending()) owner = null
  const job = { cancelled: false }
  // Keeps re-keying only while nothing has cancelled this run (a wipe, a timeout).
  const stillValid = () => !job.cancelled && !isWipePending()
  const limit = wipeTimeouts.step * 3
  const run: Promise<boolean> = Promise.all([
    withTimeout(import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.migrateLegacy(owner, stillValid)), limit, false),
    withTimeout(import('@/lib/localStore').then(({ localStore }) => localStore.migrateLegacy(owner, stillValid)), limit, false),
  ]).then((r) => {
    const ok = r.every((x) => x === true)
    // A timeout means "not finished": stop re-keying, and try again next start.
    if (!ok) job.cancelled = true
    if (ok) { try { localStorage.setItem(MIGRATED_KEY, '1') } catch { /* retried next start */ } }
    return ok
  })
  legacyMigration = run
  legacyJob = job
  void run.then(() => { if (legacyMigration === run) { legacyMigration = null; legacyJob = null } })
  return run
}

/**
 * Readers call this first. Waits for a running wipe, then says whether the
 * saved copies may be read. False means "act as if nothing is saved".
 */
export async function canReadSavedData(): Promise<boolean> {
  await waitForWipe()
  return !isWipePending() && probe().signedIn
}

/**
 * Writers call this. False when saved data must not be written: a wipe is
 * owed, or the user changed since `startedAt` (a number from getGeneration()
 * taken when the work began).
 */
export function canWriteSavedData(startedAt?: number, orgId?: string): boolean {
  if (isWipePending()) return false
  // The single choke point: nothing is ever saved when nobody is signed in or
  // no business is selected, whatever started the write and whenever it lands.
  if (!probe().signedIn) return false
  if (orgId !== undefined && NO_ORG.has(orgId)) return false
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
      const timer = setTimeout(() => resolve(false), wipeTimeouts.step)
      req.onsuccess = () => { clearTimeout(timer); resolve(true) }
      req.onerror = () => { clearTimeout(timer); resolve(false) }
      req.onblocked = () => { /* wait: it finishes when the other tab lets go, or the timer gives up */ }
    } catch { resolve(false) }
  })
}

async function doWipe(): Promise<boolean> {
  // Each store already bounds its own clear and fallback; this outer limit is
  // the last guard so a hung step counts as a failure (the wipe stays owed).
  const outer = wipeTimeouts.step * 3
  const results = await Promise.all([
    withTimeout(import('@/lib/offlineCache').then(({ offlineCache }) => offlineCache.clearAll()), outer, false),
    withTimeout(import('@/lib/localStore').then(({ localStore }) => localStore.clearAll()), outer, false),
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
  // Not queued behind an earlier wipe: that one may be stuck, and clearing
  // twice is harmless. Only the newest run may remove the owed mark (below).
  // A running legacy-entry migration is cancelled (it then only deletes) and
  // waited for briefly, so it cannot write re-keyed entries back after the wipe.
  if (legacyJob) legacyJob.cancelled = true
  const migrating = legacyMigration
  const run: Promise<boolean> = (migrating ? withTimeout(migrating, wipeTimeouts.step, false) : Promise.resolve(false))
    .then(() => doWipe())
    .catch(() => false)
    .then((ok) => {
      // Only the newest wipe may clear the owed mark; an older one finishing
      // while a newer one is running must not let readers back in early.
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

/**
 * Tell the user, in plain words, that saved data could not be cleared. Used
 * when a wipe fails on sign-out or when a different user signs in.
 */
export function reportWipeFailure(): void {
  import('@/lib/dialog').then(({ alertDialog }) =>
    alertDialog('We could not clear saved data on this device. Close the app and sign in again to finish.'),
  ).catch(() => {})
}
