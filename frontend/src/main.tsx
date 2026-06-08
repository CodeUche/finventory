import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import App from './App'
import { NotificationsProvider } from './contexts/NotificationsContext'
import { initTheme } from './hooks/useTheme'
import { useAuthStore } from './store/authStore'
import { initAnalytics } from './lib/analytics'
import './index.css'

// Apply stored theme before first render to avoid flash
initTheme()

// Initialise PostHog product analytics (no-op if VITE_POSTHOG_KEY is unset).
initAnalytics()

// ── White-label branding ──────────────────────────────────────────────────
// Fetch branding for the current hostname. On the main Audity domain the
// endpoint returns null and no changes are made. On a partner custom domain
// branding is applied via CSS variables and stored for auth page rendering.
;(async function applyWhiteLabel() {
  try {
    const host = window.location.hostname
    // Skip on localhost / Tauri (no white-label for internal builds)
    if (host === 'localhost' || host === 'tauri.localhost' || host === '127.0.0.1') return
    const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/api\/v1\/?$/, '')
    const res = await fetch(`${base}/api/v1/tenancy/white-label/?domain=${encodeURIComponent(host)}`)
    if (!res.ok) return
    const data = await res.json()
    if (!data) return
    // Apply CSS custom properties so all themed components pick them up
    if (data.primary_color) document.documentElement.style.setProperty('--brand-color', data.primary_color)
    if (data.brand_name) document.title = data.brand_name
    // Store for login page logo / tagline rendering
    ;(window as any).__WL__ = data
  } catch { /* non-fatal — main Audity brand used as fallback */ }
})()

// Unregister any PWA service workers left from previous builds.
// In the Tauri desktop app the service worker intercepts every fetch() call
// and strips the Authorization header on cross-origin requests, causing 401
// on ALL authenticated API calls after login. The new builds no longer
// register a SW, but WebView2 persists the old registration across reinstalls.
// If a SW is found we unregister it and immediately reload — the reload is
// necessary because unregister() is async and the current page's fetch events
// are still routed through the SW until the next navigation.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    if (regs.length > 0) {
      Promise.all(regs.map((r) => r.unregister())).then(() => {
        window.location.reload()
      })
    }
  })
}

// ── Session guard ──────────────────────────────────────────────────────────
// Zustand's persist middleware rehydrates SYNCHRONOUSLY from localStorage the
// moment the authStore module is imported above. Simply clearing localStorage
// is not enough — the store is already loaded in memory. We must also call
// logout() to reset the in-memory state before the first React render.
(function clearSessionOnStartup() {
  // Always clear the in-memory auth state on every app launch.
  // Saved credentials (audity-saved-creds) are kept for auto-fill on the login form.
  // "Remember me" only pre-fills credentials — it does NOT maintain a persistent session.
  useAuthStore.getState().logout()
})()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <NotificationsProvider>
        <App />
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: '#13244B',
              color: '#f8fafc',
              border: '1px solid #1E2F56',
              borderRadius: '12px',
              fontSize: '14px',
            },
            success: { iconTheme: { primary: '#22c55e', secondary: '#f8fafc' } },
            error: { iconTheme: { primary: '#ef4444', secondary: '#f8fafc' } },
          }}
        />
      </NotificationsProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
