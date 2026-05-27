/**
 * Sync Engine — replaces the simple offlineQueue.
 *
 * Improvements over offlineQueue:
 *   1. IndexedDB persistence — survives app restarts (localStorage would be lost on forced quit)
 *   2. Temp-ID chain resolution — POST responses provide the real ID; subsequent queue items
 *      that reference the temp ID in their URL or body are rewritten automatically
 *   3. Conflict detection — 4xx responses are marked as `conflict` (won't help retrying)
 *   4. Per-item retry/dismiss — subscribers get live queue state for the SyncStatusBadge
 *   5. Stuck-item recovery — on init, any item stuck in `syncing` is reset to `pending`
 */

import { openDB, type IDBPDatabase } from 'idb'

const DB_NAME = 'audity-sync-queue'
const DB_VERSION = 1
const STORE = 'queue'
const MAX_RETRIES = 3

export type SyncStatus = 'pending' | 'syncing' | 'conflict'

export interface SyncItem {
  id: string
  method: string
  url: string
  data?: unknown
  timestamp: number
  label: string
  status: SyncStatus
  retries: number
  /** The temp ID generated for an optimistic POST (e.g. "tmp_17...") */
  tempId?: string
  /** Human-readable error from last failed attempt */
  lastError?: string
  orgId: string
}

type ChangeListener = (items: SyncItem[]) => void
const _listeners = new Set<ChangeListener>()

let _db: IDBPDatabase | null = null

async function getDB(): Promise<IDBPDatabase> {
  if (_db) return _db
  _db = await openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' })
      }
    },
  })
  return _db
}

async function _load(): Promise<SyncItem[]> {
  try {
    const db = await getDB()
    return (await db.getAll(STORE)) as SyncItem[]
  } catch {
    return []
  }
}

async function _save(item: SyncItem): Promise<void> {
  try {
    const db = await getDB()
    await db.put(STORE, item)
  } catch { /* non-fatal */ }
}

async function _delete(id: string): Promise<void> {
  try {
    const db = await getDB()
    await db.delete(STORE, id)
  } catch { /* non-fatal */ }
}

async function _notify(): Promise<void> {
  const items = await _load()
  _listeners.forEach((fn) => fn(items))
}

/** Rewrite any pending/conflict queue items whose URL or body references oldId, replacing with newId */
async function _rewriteTempId(oldId: string, newId: string): Promise<void> {
  const db = await getDB()
  const all = (await db.getAll(STORE)) as SyncItem[]
  const tx = db.transaction(STORE, 'readwrite')
  for (const item of all) {
    if (item.status === 'conflict') continue   // don't touch resolved conflicts
    let changed = false
    let url = item.url
    if (url.includes(oldId)) {
      url = url.split(oldId).join(newId)
      changed = true
    }
    let data = item.data
    if (data && typeof data === 'string' && data.includes(oldId)) {
      data = data.split(oldId).join(newId)
      changed = true
    } else if (data && typeof data === 'object') {
      const str = JSON.stringify(data)
      if (str.includes(oldId)) {
        data = JSON.parse(str.split(oldId).join(newId))
        changed = true
      }
    }
    if (changed) tx.store.put({ ...item, url, data })
  }
  await tx.done
}

let _isFlushing = false

export const syncEngine = {
  /** Subscribe to queue changes. Returns an unsubscribe function. */
  subscribe(fn: ChangeListener): () => void {
    _listeners.add(fn)
    return () => _listeners.delete(fn)
  },

  /** Current queue snapshot (synchronous via in-memory snapshot is not available — use subscribe). */
  async snapshot(): Promise<SyncItem[]> {
    return _load()
  },

  /** Enqueue a mutation for later sync. */
  async enqueue(item: Omit<SyncItem, 'id' | 'timestamp' | 'label' | 'status' | 'retries' | 'orgId'> & { orgId?: string }): Promise<SyncItem> {
    const { useAuthStore } = await import('@/store/authStore')
    const orgId = item.orgId ?? useAuthStore.getState().organisation?.id ?? 'unknown'
    const clean = (item.url ?? '').split('?')[0]
    const label = `${item.method.toUpperCase()} ${clean}`
    const newItem: SyncItem = {
      ...item,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      label,
      status: 'pending',
      retries: 0,
      orgId,
    }
    await _save(newItem)
    await _notify()
    return newItem
  },

  /** Remove an item from the queue (dismiss a conflict). */
  async dismiss(id: string): Promise<void> {
    await _delete(id)
    await _notify()
  },

  /** Reset a conflict item back to pending so it will be retried on next flush. */
  async retry(id: string): Promise<void> {
    const all = await _load()
    const item = all.find((i) => i.id === id)
    if (!item) return
    await _save({ ...item, status: 'pending', retries: 0, lastError: undefined })
    await _notify()
  },

  /**
   * Flush all pending items to the server.
   * Processes in chronological order. Resolves temp IDs on successful POSTs.
   */
  async flush(): Promise<{ succeeded: number; conflicts: number }> {
    if (_isFlushing) return { succeeded: 0, conflicts: 0 }
    _isFlushing = true
    let succeeded = 0
    let conflicts = 0
    try {
      const { api } = await import('@/services/api')
      const { localStore } = await import('@/lib/localStore')
      const { useAuthStore } = await import('@/store/authStore')
      const orgId = useAuthStore.getState().organisation?.id ?? 'unknown'

      // Process pending items in order
      const all = await _load()
      const pending = all.filter((i) => i.status === 'pending').sort((a, b) => a.timestamp - b.timestamp)

      for (const item of pending) {
        // Mark as syncing
        await _save({ ...item, status: 'syncing' })
        await _notify()

        try {
          const resp = await api({
            method: item.method,
            url: item.url,
            data: item.data,
            headers: { 'X-Offline-Retry': '1' },
          })

          // Success — resolve temp ID if this was an optimistic POST
          if (item.tempId && item.method.toLowerCase() === 'post' && resp.data?.id) {
            const realId = String(resp.data.id)
            const entityType = _extractEntityType(item.url)
            if (entityType) {
              // Update localStore: replace temp with real
              await localStore.replaceTempId(orgId, entityType, item.tempId, realId)
            }
            // Rewrite any subsequent queue items referencing the temp ID
            await _rewriteTempId(item.tempId, realId)
          }

          // For online mutations, patch the in-flight cache entry with the server's real data
          if (resp.data && item.method.toLowerCase() !== 'delete') {
            const entityType = _extractEntityType(item.url)
            const recordId = item.tempId
              ? (resp.data?.id ? String(resp.data.id) : item.tempId)
              : _extractRecordId(item.url)
            if (entityType && recordId) {
              await localStore.upsert(orgId, entityType, recordId, resp.data as Record<string, unknown>)
            }
          }

          // Remove successfully synced item
          await _delete(item.id)
          succeeded++
          await _notify()
          window.dispatchEvent(new CustomEvent('audity:data-changed'))
        } catch (err: unknown) {
          const axiosErr = err as { response?: { status?: number }; message?: string }
          const status = axiosErr?.response?.status ?? 0
          const isConflict = status >= 400 && status < 500
          const newRetries = item.retries + 1
          const giveUp = isConflict || newRetries >= MAX_RETRIES

          if (giveUp) {
            const errMsg = isConflict
              ? `Server rejected (${status})`
              : `Failed after ${MAX_RETRIES} attempts`
            await _save({ ...item, status: 'conflict', retries: newRetries, lastError: errMsg })
            conflicts++
          } else {
            // Will retry on next flush
            await _save({ ...item, status: 'pending', retries: newRetries, lastError: axiosErr?.message })
          }
          await _notify()
        }
      }
    } finally {
      _isFlushing = false
    }
    return { succeeded, conflicts }
  },

  /**
   * On startup, reset any items stuck in 'syncing' state (app crashed mid-flush).
   * Call this once when the app boots.
   */
  async recoverStuck(): Promise<void> {
    const all = await _load()
    const stuck = all.filter((i) => i.status === 'syncing')
    for (const item of stuck) {
      await _save({ ...item, status: 'pending' })
    }
    if (stuck.length > 0) await _notify()
  },

  /** How many items are pending (not yet synced). */
  async pendingCount(): Promise<number> {
    const all = await _load()
    return all.filter((i) => i.status === 'pending').length
  },

  /** How many items are in conflict (need human intervention). */
  async conflictCount(): Promise<number> {
    const all = await _load()
    return all.filter((i) => i.status === 'conflict').length
  },
}

// ── URL helpers (exported so api.ts can import them) ──────────────────────────

/** Extract entity type from a REST URL: `/payroll/employees/abc/` → `employees` */
export function _extractEntityType(url: string): string | null {
  const clean = url.split('?')[0].replace(/\/$/, '')
  const parts = clean.split('/').filter(Boolean)
  if (parts.length === 0) return null
  const lastPart = parts[parts.length - 1]
  if (_isUuid(lastPart) || _isActionName(lastPart, parts)) {
    return parts[parts.length - 2] ?? null
  }
  return lastPart
}

/** Extract record UUID from a REST URL: `/payroll/employees/abc/` → `abc` */
export function _extractRecordId(url: string): string | null {
  const clean = url.split('?')[0].replace(/\/$/, '')
  const parts = clean.split('/').filter(Boolean)
  // Walk from the end to find the first UUID
  for (let i = parts.length - 1; i >= 0; i--) {
    if (_isUuid(parts[i])) return parts[i]
  }
  return null
}

/**
 * Detect RPC-style action endpoints.
 * Pattern: /entity/uuid/action_name/ — the last segment is a verb, not a resource.
 * These should NOT be optimistically handled.
 */
export function isActionEndpoint(url: string): boolean {
  const clean = url.split('?')[0].replace(/\/$/, '')
  const parts = clean.split('/').filter(Boolean)
  if (parts.length < 3) return false
  const last = parts[parts.length - 1]
  const secondLast = parts[parts.length - 2]
  return _isUuid(secondLast) && !_isUuid(last)
}

/** Strip the trailing UUID segment to get the collection/list URL. */
export function buildListUrl(url: string): string {
  const clean = url.split('?')[0]
  return clean.replace(/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/?$/, '/')
}

function _isUuid(s: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)
}

function _isActionName(s: string, allParts: string[]): boolean {
  // If the preceding segment is a UUID, the current segment is an action
  const idx = allParts.indexOf(s)
  if (idx <= 0) return false
  return _isUuid(allParts[idx - 1])
}
