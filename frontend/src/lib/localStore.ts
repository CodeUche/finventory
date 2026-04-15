/**
 * Local entity store — IndexedDB backed.
 *
 * Stores optimistic copies of records so offline GET requests
 * can serve data that includes local creates, edits, and deletes.
 *
 * Key pattern: `${orgId}:${entityType}:${recordId}`
 * Index: composite `[_orgId, _entityType]` for list queries.
 */

import { openDB, type IDBPDatabase } from 'idb'

const DB_NAME = 'audity-local-store'
const DB_VERSION = 1
const STORE = 'entities'

interface EntityRecord {
  _key: string          // ${orgId}:${entityType}:${recordId}
  _orgId: string
  _entityType: string
  _recordId: string
  _isDeleted: boolean   // soft-delete for optimistic deletes
  _syncedAt?: number    // set when real server response patches this record
  [field: string]: unknown
}

let _db: IDBPDatabase | null = null

async function getDB(): Promise<IDBPDatabase> {
  if (_db) return _db
  _db = await openDB(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: '_key' })
        store.createIndex('byOrgEntity', ['_orgId', '_entityType'])
      }
    },
  })
  return _db
}

function makeKey(orgId: string, entityType: string, recordId: string): string {
  return `${orgId}:${entityType}:${recordId}`
}

export const localStore = {
  /** Insert or overwrite a single record. */
  async upsert(orgId: string, entityType: string, recordId: string, data: Record<string, unknown>): Promise<void> {
    try {
      const db = await getDB()
      const record: EntityRecord = {
        ...data,
        _key: makeKey(orgId, entityType, recordId),
        _orgId: orgId,
        _entityType: entityType,
        _recordId: recordId,
        _isDeleted: false,
      }
      await db.put(STORE, record)
    } catch { /* non-fatal */ }
  },

  /** Bulk upsert — used when seeding cache from a successful list response. */
  async upsertMany(orgId: string, entityType: string, records: Array<Record<string, unknown>>, idField = 'id'): Promise<void> {
    try {
      const db = await getDB()
      const tx = db.transaction(STORE, 'readwrite')
      for (const r of records) {
        const id = String(r[idField] ?? '')
        if (!id) continue
        const record: EntityRecord = {
          ...r,
          _key: makeKey(orgId, entityType, id),
          _orgId: orgId,
          _entityType: entityType,
          _recordId: id,
          _isDeleted: false,
        }
        tx.store.put(record)
      }
      await tx.done
    } catch { /* non-fatal */ }
  },

  /** Mark a record as deleted (optimistic delete). */
  async remove(orgId: string, entityType: string, recordId: string): Promise<void> {
    try {
      const db = await getDB()
      const key = makeKey(orgId, entityType, recordId)
      const existing = await db.get(STORE, key) as EntityRecord | undefined
      if (existing) {
        await db.put(STORE, { ...existing, _isDeleted: true })
      } else {
        // Create a tombstone so we know it was deleted
        await db.put(STORE, {
          _key: key, _orgId: orgId, _entityType: entityType,
          _recordId: recordId, _isDeleted: true,
        })
      }
    } catch { /* non-fatal */ }
  },

  /** Get all non-deleted records for an entity type within an org. */
  async getAll(orgId: string, entityType: string): Promise<EntityRecord[]> {
    try {
      const db = await getDB()
      const results = await db.getAllFromIndex(STORE, 'byOrgEntity', [orgId, entityType]) as EntityRecord[]
      return results.filter((r) => !r._isDeleted)
    } catch {
      return []
    }
  },

  /** Get a single record. Returns null if not found or deleted. */
  async getOne(orgId: string, entityType: string, recordId: string): Promise<EntityRecord | null> {
    try {
      const db = await getDB()
      const record = await db.get(STORE, makeKey(orgId, entityType, recordId)) as EntityRecord | undefined
      if (!record || record._isDeleted) return null
      return record
    } catch {
      return null
    }
  },

  /**
   * Replace all occurrences of a temp ID with the real server-assigned ID.
   * Called after a POST syncs successfully.
   */
  async replaceTempId(orgId: string, entityType: string, tempId: string, realId: string): Promise<void> {
    try {
      const db = await getDB()
      const tempKey = makeKey(orgId, entityType, tempId)
      const existing = await db.get(STORE, tempKey) as EntityRecord | undefined
      if (!existing) return
      const tx = db.transaction(STORE, 'readwrite')
      // Delete the temp entry
      tx.store.delete(tempKey)
      // Insert with real ID
      tx.store.put({
        ...existing,
        _key: makeKey(orgId, entityType, realId),
        _recordId: realId,
        _syncedAt: Date.now(),
      })
      await tx.done
    } catch { /* non-fatal */ }
  },

  /** Clear all records for an org (used on logout or org switch). */
  async clearOrg(orgId: string): Promise<void> {
    try {
      const db = await getDB()
      const all = await db.getAll(STORE) as EntityRecord[]
      const tx = db.transaction(STORE, 'readwrite')
      for (const r of all) {
        if (r._orgId === orgId) tx.store.delete(r._key)
      }
      await tx.done
    } catch { /* non-fatal */ }
  },

  /** Wipe everything (used on full logout). */
  async clearAll(): Promise<void> {
    try {
      const db = await getDB()
      await db.clear(STORE)
    } catch { /* non-fatal */ }
  },
}
