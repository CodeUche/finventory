import { describe, it, expect } from 'vitest'
import { shouldClearCache } from '@/lib/cacheOwner'
import { hasAnyModulePermission } from '@/pages/dashboard/DashboardPage'

describe('shouldClearCache', () => {
  it('keeps the cache for the same user, online or offline', () => {
    expect(shouldClearCache('u1', 'u1', true)).toBe(false)
    expect(shouldClearCache('u1', 'u1', false)).toBe(false)
  })
  it('clears it when a different user signs in', () => {
    expect(shouldClearCache('u1', 'u2', true)).toBe(true)
    expect(shouldClearCache('u1', 'u2', false)).toBe(true)
  })
  it('with an unknown owner, clears only when online', () => {
    expect(shouldClearCache(null, 'u2', true)).toBe(true)
    expect(shouldClearCache(null, 'u2', false)).toBe(false)
  })
})

describe('hasAnyModulePermission', () => {
  it('is false with no or only "none" permissions', () => {
    expect(hasAnyModulePermission({})).toBe(false)
    expect(hasAnyModulePermission({ sales: 'none' })).toBe(false)
  })
  it('is true when any module is granted', () => {
    expect(hasAnyModulePermission({ customers: 'view' })).toBe(true)
    expect(hasAnyModulePermission({ sales: 'none', payroll: 'write' })).toBe(true)
  })
})
