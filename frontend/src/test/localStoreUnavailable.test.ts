/**
 * When IndexedDB cannot be opened at all, wiping must never throw. Lives in
 * its own file because it resets the module registry.
 */
import { describe, it, expect, vi } from 'vitest'

vi.mock('idb', () => ({ openDB: vi.fn(async () => { throw new Error('IndexedDB blocked') }) }))

describe('IndexedDB unavailable', () => {
  it('clearing resolves instead of throwing, and sign-in still works', async () => {
    vi.resetModules()
    // No indexedDB global: nothing can be stored, so there is nothing left to clear.
    vi.stubGlobal('indexedDB', undefined)
    const { openDB } = await import('idb')
    const { clearLocalReadData, claimCacheForUser } = await import('@/lib/cacheOwner')
    await expect(clearLocalReadData()).resolves.toBe(true)
    await expect(claimCacheForUser('someone')).resolves.toBeUndefined()
    expect(openDB).toHaveBeenCalled() // the failing open really was what the stores used
    vi.unstubAllGlobals()
  })

  it('reports failure (and stays owed) when the database cannot be deleted either', async () => {
    vi.resetModules()
    vi.stubGlobal('indexedDB', {
      deleteDatabase: () => { const r: any = {}; setTimeout(() => r.onerror?.(), 0); return r },
    })
    const { clearLocalReadData } = await import('@/lib/cacheOwner')
    const { isWipePending } = await import('@/lib/localDataGuard')
    await expect(clearLocalReadData()).resolves.toBe(false)
    expect(isWipePending()).toBe(true)
    vi.unstubAllGlobals()
  })
})
