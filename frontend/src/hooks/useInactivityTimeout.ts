import { useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'
import toast from 'react-hot-toast'

export type TimeoutOption = 'never' | '30m' | '1h' | '4h'

const TIMEOUT_KEY = 'finventory-inactivity-timeout'
const LAST_ACTIVE_KEY = 'finventory-last-active'
const SESSION_START_KEY = 'finventory-session-start'

// Absolute ceiling: even 'never' users are logged out after this
const ABSOLUTE_SESSION_MS = 12 * 60 * 60 * 1000  // 12 hours

export function getTimeoutMs(opt: TimeoutOption): number | null {
  const map: Record<Exclude<TimeoutOption, 'never'>, number> = {
    '30m': 30 * 60 * 1000,
    '1h': 60 * 60 * 1000,
    '4h': 4 * 60 * 60 * 1000,
  }
  return opt === 'never' ? null : (map[opt] ?? null)
}

export function getTimeoutPreference(): TimeoutOption {
  return (localStorage.getItem(TIMEOUT_KEY) as TimeoutOption) ?? '30m'
}

export function setTimeoutPreference(opt: TimeoutOption) {
  localStorage.setItem(TIMEOUT_KEY, opt)
}

export function useInactivityTimeout() {
  const { isAuthenticated, logout } = useAuthStore()
  const navigate = useNavigate()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const doLogout = useCallback(async (message: string) => {
    try {
      const currentRefresh = useAuthStore.getState().tokens?.refresh
      if (currentRefresh) await authApi.logout(currentRefresh)
    } catch { /* ignore network errors */ }
    localStorage.removeItem(LAST_ACTIVE_KEY)
    localStorage.removeItem(SESSION_START_KEY)
    logout()
    toast(message, { icon: '🔒', duration: 5000 })
    navigate('/login')
  }, [logout, navigate])

  const reset = useCallback(() => {
    if (!isAuthenticated) return
    localStorage.setItem(LAST_ACTIVE_KEY, String(Date.now()))

    const ms = getTimeoutMs(getTimeoutPreference())
    if (timerRef.current) clearTimeout(timerRef.current)
    if (ms !== null) {
      timerRef.current = setTimeout(() => {
        doLogout('Session expired due to inactivity. Please sign in again.')
      }, ms)
    }
  }, [isAuthenticated, doLogout])

  useEffect(() => {
    if (!isAuthenticated) return

    // ── On mount: check if user was idle before this page load ────────────────
    const now = Date.now()
    const lastActive = parseInt(localStorage.getItem(LAST_ACTIVE_KEY) ?? '0', 10)
    const sessionStart = parseInt(localStorage.getItem(SESSION_START_KEY) ?? '0', 10)

    // First visit / fresh login — stamp timestamps
    if (!lastActive) localStorage.setItem(LAST_ACTIVE_KEY, String(now))
    if (!sessionStart) localStorage.setItem(SESSION_START_KEY, String(now))

    // Check inactivity gap (handles browser-close → reopen scenario)
    if (lastActive) {
      const idleMs = now - lastActive
      const pref = getTimeoutPreference()
      const limitMs = getTimeoutMs(pref)
      if (limitMs !== null && idleMs >= limitMs) {
        doLogout('Session expired due to inactivity. Please sign in again.')
        return
      }
    }

    // Check absolute session ceiling
    if (sessionStart && now - sessionStart >= ABSOLUTE_SESSION_MS) {
      doLogout('Your session has expired (12 hours). Please sign in again.')
      return
    }

    // ── In-session: listen to activity events ─────────────────────────────────
    const events = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'] as const
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }))
    reset()

    // Also enforce absolute ceiling with a timer
    const remaining = ABSOLUTE_SESSION_MS - (sessionStart ? Date.now() - sessionStart : 0)
    const absoluteTimer = setTimeout(() => {
      doLogout('Your session has expired (12 hours). Please sign in again.')
    }, Math.max(0, remaining))

    return () => {
      events.forEach((e) => window.removeEventListener(e, reset))
      if (timerRef.current) clearTimeout(timerRef.current)
      clearTimeout(absoluteTimer)
    }
  }, [isAuthenticated, reset, doLogout])
}
