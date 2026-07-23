import { useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { syncEngine } from '@/lib/syncEngine'
import { flushQueuedMutations } from '@/lib/syncFlush'
import { useAuthStore } from '@/store/authStore'

// A SINGLE toast slot for every connectivity-status message. Because both the
// browser's native online/offline events AND the synthetic ones dispatched by
// services/api.ts (the Tauri/WebView2 reachability workaround) drive this hook,
// a flapping connection used to stack a fresh "Back online" toast on every
// cycle — filling the screen. Reusing one id guarantees at most one is visible.
const NET_TOAST_ID = 'net-status'

// How long the connection must stay up before we run the (expensive) reconnect
// work. A later offline event cancels the pending run, so we never flush or hit
// the verifier endpoint mid-flap.
const RECONNECT_SETTLE_MS = 800

/**
 * Returns `true` when the browser reports network connectivity.
 *
 * Side effects (debounced + de-duplicated so a flapping connection can't spam):
 * - Shows a single toast banner when going offline or back online.
 * - On a *settled* reconnect, flushes any queued mutations via syncEngine.
 * - On app boot, recovers any items stuck in `syncing` state (app crashed mid-flush).
 */
export function useNetworkStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)
  // The connectivity state we last *acted on*. Redundant events (native +
  // synthetic firing for the same transition) are ignored so the reconnect
  // work and toast run once per genuine offline→online edge, not per event.
  const actedOnlineRef = useRef(navigator.onLine)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectingRef = useRef(false)

  useEffect(() => {
    // Recover stuck items once on mount
    syncEngine.recoverStuck().catch(() => {/* non-fatal */})

    const clearTimer = () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current)
        reconnectTimer.current = null
      }
    }

    const handleOffline = () => {
      setOnline(false)
      if (!actedOnlineRef.current) return // already offline — ignore duplicate event
      actedOnlineRef.current = false
      clearTimer() // cancel any pending reconnect — the connection dropped again
      // AppLayout already shows the amber offline banner — no separate toast needed.
      toast.dismiss('offline-status')
    }

    const doReconnect = async () => {
      if (reconnectingRef.current) return // a reconnect is already in flight
      reconnectingRef.current = true
      try {
        const authState = useAuthStore.getState()

        // Offline grace session (PBKDF2 unlock, no tokens): do NOT log out — a
        // trader mid-sale must not lose their screen because the internet
        // flickered back. First try a SILENT resume: the password typed at
        // unlock also decrypted the stored refresh token, so we can usually
        // trade it for fresh JWTs and upgrade the session in place — no banner,
        // no re-login. Only when that fails (no stored token, 7+ days offline,
        // password changed elsewhere) does the non-blocking "sign in to sync"
        // banner appear; the flush then fires after the next online login.
        if (authState.isAuthenticated && authState.isOfflineSession) {
          const { trySilentResume } = await import('@/lib/offlineResume')
          const resumed = await trySilentResume()
          if (resumed) {
            toast.success('Back online — reconnected.', { id: NET_TOAST_ID, duration: 3000 })
            await flushQueuedMutations()
          }
          // If resume wasn't possible (no stored refresh token, 7+ days offline,
          // or password changed elsewhere), AppLayout shows a single persistent
          // "sign in to sync" banner — no toast here, to avoid the duplicate
          // messaging the user saw (banner + toast + error all at once).
          return
        }

        // Check whether the server-side offline verifier was revoked while offline
        // (e.g. password changed on another device). Purge the local blob if so.
        // Real-token sessions only — an offline grace session has no tokens to ask with.
        if (authState.isAuthenticated) {
          try {
            const { authApi } = await import('@/services/api')
            const { data } = await authApi.getOfflineVerifierStatus()
            if (!data.active) {
              const { deleteVerifier } = await import('@/lib/offlineVerifier')
              await deleteVerifier()
            }
          } catch { /* non-fatal — keep existing blob */ }
        }

        const pending = await syncEngine.pendingCount()
        if (pending === 0) {
          toast.success('Back online', { id: NET_TOAST_ID, duration: 2500 })
          return
        }
        await flushQueuedMutations()
      } finally {
        reconnectingRef.current = false
      }
    }

    const handleOnline = () => {
      if (actedOnlineRef.current) return // already online — ignore duplicate event
      actedOnlineRef.current = true
      toast.dismiss('offline-status')

      // Debounce: wait for the connection to HOLD before flipping the UI back
      // online and doing the heavy reconnect work. `online` is a dependency of
      // several AppLayout data-fetch effects, so flipping it on every flap would
      // trigger a re-fetch storm (flashing skeletons). We flip to offline
      // immediately (above, in handleOffline) but back to online only once
      // settled — so a flapping connection produces exactly one reconnect.
      clearTimer()
      reconnectTimer.current = setTimeout(() => {
        reconnectTimer.current = null
        // Bail if connectivity was lost again while we waited.
        if (!actedOnlineRef.current) return
        setOnline(true)
        void doReconnect()
      }, RECONNECT_SETTLE_MS)
    }

    window.addEventListener('offline', handleOffline)
    window.addEventListener('online', handleOnline)
    return () => {
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('online', handleOnline)
      clearTimer()
    }
  }, [])

  return online
}
