/**
 * Theme hook — persists 'dark' | 'light' to localStorage and applies
 * the corresponding class to the <html> element.
 *
 * Usage:
 *   const { theme, setTheme } = useTheme()
 */

const STORAGE_KEY = 'finventory-theme'

export type Theme = 'dark' | 'light'

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
