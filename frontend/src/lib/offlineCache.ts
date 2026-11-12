/**
 * Offline read cache — IndexedDB backed.
 *
 * Strategy: Network-first.
 *   • Every successful GET response is written to the cache.
 *   • When the device is offline, GET requests are served from the cache
 *     instead of failing with a network error.
 *
 * Cache key: `${orgId}||${url_with_query_params}`
 *   Scoping to orgId ensures users who switch organisations never see
 *   another org's stale data.
 */

import { openDB, type IDBPDatabase } from 'idb'
import { useAuthStore } from '@/store/authStore'
import { canReadSavedData, canWriteSavedData, deleteDatabaseByName, wipeTimeouts, withTimeout, getSessionInfo, isIdentityUrl } from '@/lib/localDataGuard'

const DB_NAME = 'audity-offline-cache'
const DB_VERSION = 1
const STORE = 'responses'

interface CacheEntry {
  key: string
  data: unknown
  cachedAt: number  // Unix ms — used to show "data from X ago" in UI
  url: string
}

let _db: IDBPDatabase | null = null

async function getDB(): Promise<IDBPDatabase> {
  if (_db) return _db
  _db = await openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'key' })
      }
    },
  })
  return _db
}

function currentOrgId(): string {
  return useAuthStore.getState().organisation?.id ?? 'anonymous'
}

// Entries are scoped to business AND user, so one user can never read another's.
function scopePrefix(orgId?: string): string {
  return `${orgId ?? currentOrgId()}|${getSessionInfo().userId ?? 'nouser'}||`
}

function makeKey(url: string, orgId?: string): string {
  return `${scopePrefix(orgId)}${url}`
}

export const offlineCache = {
  /** Write a successful GET response into the cache. */
  async set(url: string, data: unknown, startedAt?: number, orgId?: string): Promise<void> {
    try {
      // Never write while a wipe is owed, or when the user changed since this work began.
      if (isIdentityUrl(url)) return
      // `orgId` is the business the request was made for (captured when it started).
      if (!canWriteSavedData(startedAt, orgId ?? currentOrgId())) return
      const db = await getDB()
      const key = makeKey(url, orgId)
      await db.put(STORE, { key, data, cachedAt: Date.now(), url } satisfies CacheEntry)
    } catch {
      // Non-fatal — cache write failures should never surface to the user
    }
  },

  /** Read a cached response. Returns null if not found. */
  async get(url: string, orgId?: string): Promise<CacheEntry | null> {
    try {
      if (isIdentityUrl(url)) return null
      if (!(await canReadSavedData())) return null
      const db = await getDB()
      const entry = await db.get(STORE, makeKey(url, orgId)) as CacheEntry | undefined
      return entry ?? null
    } catch {
      return null
    }
  },

  /**
   * Return the oldest cachedAt timestamp across all entries for the current org.
   * Used by the UI to show "data from X ago".
   */
  async oldestCachedAt(): Promise<number | null> {
    try {
      if (!(await canReadSavedData())) return null
      const db = await getDB()
      const orgPrefix = scopePrefix()
      const all = (await db.getAll(STORE)) as CacheEntry[]
      const orgEntries = all.filter((e) => e.key.startsWith(orgPrefix))
      if (orgEntries.length === 0) return null
      return Math.min(...orgEntries.map((e) => e.cachedAt))
    } catch {
      return null
    }
  },

  /** Clear all cached entries for the current organisation. */
  async clearOrg(): Promise<void> {
    try {
      const db = await getDB()
      const orgPrefix = scopePrefix()
      const all = (await db.getAll(STORE)) as CacheEntry[]
      const tx = db.transaction(STORE, 'readwrite')
      for (const entry of all) {
        if (entry.key.startsWith(orgPrefix)) tx.store.delete(entry.key)
      }
      await tx.done
    } catch { /* non-fatal */ }
  },

  /**
   * Convert entries saved before they were scoped to a user (key `org||url`).
   * With a known owner they are re-keyed to that owner, otherwise deleted.
   * Identity URLs and the "anonymous" business are always deleted. Returns
   * true when finished.
   */
  async migrateLegacy(owner: string | null): Promise<boolean> {
    try {
      const db = await getDB()
      const all = (await db.getAll(STORE)) as CacheEntry[]
      for (const e of all) {
        const cut = e.key.indexOf('||')
        const head = cut < 0 ? e.key : e.key.slice(0, cut)
        if (head.includes('|')) continue // already user-scoped
        await db.delete(STORE, e.key)
        const url = cut < 0 ? e.url : e.key.slice(cut + 2)
        if (!owner || head === 'anonymous' || isIdentityUrl(url)) continue
        await db.put(STORE, { ...e, key: `${head}|${owner}||${url}` })
      }
      return true
    } catch {
      return false
    }
  },

  /** Wipe the entire cache (used on logout). */
  async clearAll(): Promise<boolean> {
    try {
      // Bounded: a stalled open or a clear held up by another tab counts as failed.
      const done = await withTimeout((async () => { const db = await getDB(); await db.clear(STORE); return true })(), wipeTimeouts.step, false)
      if (done) return true
    } catch { /* fall back to deleting the whole database */ }
    try { _db?.close() } catch { /* already closed */ }
    _db = null
    return deleteDatabaseByName(DB_NAME)
  },

  /**
   * Delete all cache entries for the current org whose URL starts with urlPrefix.
   * Call this after successful mutations so the next GET hits the network for fresh data.
   */
  async invalidatePrefix(urlPrefix: string): Promise<void> {
    try {
      const db = await getDB()
      const orgPrefix = scopePrefix()
      const all = (await db.getAll(STORE)) as CacheEntry[]
      const tx = db.transaction(STORE, 'readwrite')
      for (const entry of all) {
        if (!entry.key.startsWith(orgPrefix)) continue
        const entryUrl = entry.key.slice(orgPrefix.length)
        if (entryUrl.startsWith(urlPrefix)) tx.store.delete(entry.key)
      }
      await tx.done
    } catch { /* non-fatal */ }
  },
}

/** Human-readable "X minutes ago" / "X hours ago" string from a Unix-ms timestamp. */
export function timeAgo(ms: number): string {
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}
