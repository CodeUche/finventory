/**
 * Theme hook — persists 'dark' | 'light' to localStorage and applies
 * the corresponding class to the <html> element.
 *
 * Usage:
 *   const { theme, setTheme } = useTheme()
 */

import { useEffect, useState } from 'react'

const STORAGE_KEY = 'finventory-theme'

export type Theme = 'dark' | 'light'

/** Brand accent for charts/SVG that can't read CSS vars via attributes:
 *  gold in dark, navy in light. Re-renders on theme toggle. */
export function useThemeAccent(): string {
  const [light, setLight] = useState<boolean>(() => getStoredTheme() === 'light')
  useEffect(() => {
    const handler = (e: Event) => setLight((e as CustomEvent<Theme>).detail === 'light')
    window.addEventListener('themechange', handler)
    return () => window.removeEventListener('themechange', handler)
  }, [])
  return light ? '#1C2F5C' : '#D4A017'
}

function applyTheme(theme: Theme) {
  const html = document.documentElement
  if (theme === 'light') {
    html.classList.add('light')
    html.classList.remove('dark')
  } else {
    html.classList.add('dark')
    html.classList.remove('light')
  }
}

export function getStoredTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch { /* ignore */ }
  return 'dark'
}

export function initTheme() {
  applyTheme(getStoredTheme())
}

export function setTheme(theme: Theme) {
  try { localStorage.setItem(STORAGE_KEY, theme) } catch { /* ignore */ }
  applyTheme(theme)
  window.dispatchEvent(new CustomEvent('themechange', { detail: theme }))
}
