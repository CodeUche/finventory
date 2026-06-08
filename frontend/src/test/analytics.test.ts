/**
 * Analytics URL-sanitization unit tests — Vitest
 *
 * These guard the security-critical scrubbing that keeps auth tokens out of
 * PostHog. If any of these regress, secrets could leak to a third party.
 */

import { describe, it, expect } from 'vitest'
import { sanitizeUrl } from '@/lib/analytics'

describe('sanitizeUrl', () => {
  it('redacts invite token path segments (bare path)', () => {
    expect(sanitizeUrl('/accept-invite/abc123secret')).toBe('/accept-invite/:token')
    expect(sanitizeUrl('/reject-invite/9f8e7d6c')).toBe('/reject-invite/:token')
  })

  it('redacts invite token path segments (absolute URL, keeps host)', () => {
    expect(sanitizeUrl('http://tauri.localhost/accept-invite/abc123'))
      .toBe('http://tauri.localhost/accept-invite/:token')
  })

  it('redacts sensitive query params but keeps the key for grouping', () => {
    expect(sanitizeUrl('/verify-email?token=supersecret')).toBe('/verify-email?token=%3Aredacted')
    expect(sanitizeUrl('/reset?code=123&email=a%40b.com'))
      .toBe('/reset?code=%3Aredacted&email=%3Aredacted')
  })

  it('preserves non-sensitive paths and query params untouched', () => {
    expect(sanitizeUrl('/dashboard')).toBe('/dashboard')
    expect(sanitizeUrl('/sales?status=paid&page=2')).toBe('/sales?status=paid&page=2')
  })

  it('redacts both a token path AND a sensitive query param together', () => {
    expect(sanitizeUrl('/accept-invite/tok123?email=a%40b.com'))
      .toBe('/accept-invite/:token?email=%3Aredacted')
  })

  it('is case-insensitive on the token path prefix (token still redacted)', () => {
    const out = sanitizeUrl('/Accept-Invite/abcSECRET')
    expect(out).toContain(':token')
    expect(out).not.toContain('abcSECRET')
  })

  it('redacts secrets even from messy/unexpected input (never leaks)', () => {
    const out = sanitizeUrl('not a url ?token=leakme')
    expect(out).not.toContain('leakme')
  })

  it('returns empty / non-string input unchanged', () => {
    expect(sanitizeUrl('')).toBe('')
    // @ts-expect-error — runtime guard against non-string input
    expect(sanitizeUrl(undefined)).toBe(undefined)
  })
})
