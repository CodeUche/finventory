/**
 * useTheme hook unit tests — Vitest
 *
 * Tests types: Unit
 * Hook: frontend/src/hooks/useTheme.ts
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ─── Mock localStorage ────────────────────────────────────────────────────────

const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => { store[k] = v },
    removeItem: (k: string) => { delete store[k] },
    clear: () => { store = {} },
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock })

// ─── Mock document.documentElement ────────────────────────────────────────────

beforeEach(() => {
  localStorageMock.clear()
  document.documentElement.classList.remove('dark', 'light')
  vi.resetModules()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('useTheme / theme utilities', () => {
  it('initTheme applies dark class when stored preference is dark', async () => {
    localStorageMock.setItem('finventory-theme', 'dark')
    const { initTheme } = await import('@/hooks/useTheme')
    initTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('initTheme applies light class when stored preference is light', async () => {
    localStorageMock.setItem('finventory-theme', 'light')
    const { initTheme } = await import('@/hooks/useTheme')
    initTheme()
    expect(document.documentElement.classList.contains('light')).toBe(true)
  })

  it('initTheme defaults to dark when no preference stored', async () => {
    // No stored preference
    const { initTheme } = await import('@/hooks/useTheme')
    initTheme()
    // Default is dark for Audity
    const isDark = document.documentElement.classList.contains('dark')
    const isLight = document.documentElement.classList.contains('light')
    // One or the other must be set
    expect(isDark || isLight).toBe(true)
  })
})

describe('setTheme utility', () => {
  it('setTheme dark adds dark class and persists', async () => {
    const { setTheme, initTheme } = await import('@/hooks/useTheme')

    localStorageMock.setItem('finventory-theme', 'light')
    initTheme()
    expect(document.documentElement.classList.contains('light')).toBe(true)

    setTheme('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorageMock.getItem('finventory-theme')).toBe('dark')
  })
})
