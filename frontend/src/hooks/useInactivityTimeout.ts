import { useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { authApi } from '@/services/api'

export type TimeoutOption = 'never' | '30m' | '1h' | '4h'

const TIMEOUT_KEY = 'finventory-inactivity-timeout'

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

  const reset = useCallback(() => {
    if (!isAuthenticated) return
    const ms = getTimeoutMs(getTimeoutPreference())
    if (ms === null) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      try {
        // Read current tokens at logout time (not stale closure value)
        const currentRefresh = useAuthStore.getState().tokens?.refresh
        if (currentRefresh) await authApi.logout(currentRefresh)
      } catch {
        // ignore network errors on forced logout
      }
      logout()
      navigate('/login')
    }, ms)
  }, [isAuthenticated, logout, navigate])  // removed `tokens` — read at logout time instead

  useEffect(() => {
    if (!isAuthenticated) return
    const events = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'] as const
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }))
    reset()
    return () => {
      events.forEach((e) => window.removeEventListener(e, reset))
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [isAuthenticated, reset])
}
