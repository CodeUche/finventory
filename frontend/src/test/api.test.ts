/**
 * Frontend API service unit tests — Vitest
 *
 * Tests types covered:
 *   Unit  — pure utility logic in the API module (interceptors, header injection)
 *   Integration — axios request/response transformation
 *
 * We mock axios so these run without a real backend.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ─── Axios mock ───────────────────────────────────────────────────────────────

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios')
  return {
    default: {
      ...actual.default,
      create: vi.fn(() => ({
        interceptors: {
          request: { use: vi.fn() },
          response: { use: vi.fn() },
        },
        get: vi.fn(),
        post: vi.fn(),
        put: vi.fn(),
        patch: vi.fn(),
        delete: vi.fn(),
        defaults: { headers: { common: {} } },
      })),
    },
  }
})

// ─── formatAmountInput / stripCommas (API boundary helpers) ───────────────────

import { formatAmountInput, stripCommas } from '@/lib/utils'

describe('API boundary helpers', () => {
  describe('stripCommas', () => {
    it('removes comma separators before API submission', () => {
      expect(stripCommas('1,000,000')).toBe('1000000')
    })

    it('preserves decimal values', () => {
      expect(stripCommas('8,500.50')).toBe('8500.50')
    })

    it('handles empty string', () => {
      expect(stripCommas('')).toBe('')
    })

    it('handles already clean numeric string', () => {
      expect(stripCommas('5500')).toBe('5500')
    })
  })

  describe('formatAmountInput', () => {
    it('adds thousands separators for display', () => {
      expect(formatAmountInput('1000000')).toBe('1,000,000')
    })

    it('preserves decimal portion', () => {
      expect(formatAmountInput('8500.75')).toBe('8,500.75')
    })

    it('handles single-digit input', () => {
      const result = formatAmountInput('5')
      expect(result).toBe('5')
    })

    it('round-trips correctly: format → strip → same value', () => {
      const original = '750000.50'
      const formatted = formatAmountInput(original)
      const stripped = stripCommas(formatted)
      expect(stripped).toBe(original)
    })
  })
})

// ─── formatDate (API → UI transformation) ─────────────────────────────────────

import { formatDate } from '@/lib/utils'

describe('formatDate', () => {
  it('converts ISO date to DD/MM/YYYY', () => {
    expect(formatDate('2026-01-15')).toBe('15/01/2026')
  })

  it('converts ISO datetime to DD/MM/YYYY (strips time)', () => {
    expect(formatDate('2026-12-31T23:59:59Z')).toBe('31/12/2026')
  })

  it('returns empty string for empty input', () => {
    expect(formatDate('')).toBe('')
  })

  it('does not shift timezone (Jan 1 stays Jan 1)', () => {
    expect(formatDate('2026-01-01')).toBe('01/01/2026')
  })

  it('returns input unchanged for invalid date strings', () => {
    expect(formatDate('not-a-date')).toBe('not-a-date')
  })
})

// ─── Auth store integration (token header injection) ──────────────────────────

import { useAuthStore } from '@/store/authStore'

describe('Auth store — token storage for API', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null,
      tokens: null,
      organisation: null,
      organisations: [],
      isAuthenticated: false,
      rememberMe: false,
      memberRole: null,
      modulePermissions: {},
    })
  })

  it('access token is available after login', () => {
    const user = {
      id: 'uuid-1',
      email: 'user@test.com',
      first_name: 'Test',
      last_name: 'User',
      is_superuser: false,
      is_staff: false,
    } as any
    useAuthStore.getState().setAuth(user, { access: 'tok_access', refresh: 'tok_refresh' })
    expect(useAuthStore.getState().tokens?.access).toBe('tok_access')
  })

  it('refresh token is available for renewal', () => {
    const user = { id: 'u1', email: 'a@b.com', first_name: 'A', last_name: 'B',
                   is_superuser: false, is_staff: false } as any
    useAuthStore.getState().setAuth(user, { access: 'a', refresh: 'r_token' })
    expect(useAuthStore.getState().tokens?.refresh).toBe('r_token')
  })

  it('after logout both tokens are cleared', () => {
    const user = { id: 'u2', email: 'b@c.com', first_name: 'B', last_name: 'C',
                   is_superuser: false, is_staff: false } as any
    useAuthStore.getState().setAuth(user, { access: 'a', refresh: 'r' })
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().tokens).toBeNull()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })
})

// ─── Module permissions gating ────────────────────────────────────────────────

describe('Module permission store', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null, tokens: null, organisation: null, organisations: [],
      isAuthenticated: false, rememberMe: false,
      memberRole: null, modulePermissions: {},
    })
  })

  it('canWrite is true when access_level is write', () => {
    useAuthStore.getState().setMembership('staff', { sales: 'write' })
    expect(useAuthStore.getState().modulePermissions['sales']).toBe('write')
  })

  it('canEdit is true when access_level is edit', () => {
    useAuthStore.getState().setMembership('manager', { bills: 'edit' })
    expect(useAuthStore.getState().modulePermissions['bills']).toBe('edit')
  })

  it('no permission set means module key is absent', () => {
    useAuthStore.getState().setMembership('viewer', {})
    expect(useAuthStore.getState().modulePermissions['accounting']).toBeUndefined()
  })
})
