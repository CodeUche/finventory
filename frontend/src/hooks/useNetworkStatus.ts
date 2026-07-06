import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { syncEngine } from '@/lib/syncEngine'
import { flushQueuedMutations } from '@/lib/syncFlush'
import { useAuthStore } from '@/store/authStore'

/**
 * Returns `true` when the browser reports network connectivity.
 *
 * Side effects:
 * - Shows a toast banner when going offline or back online.
 * - On reconnect, flushes any queued mutations via syncEngine.
 * - On app boot, recovers any items stuck in `syncing` state (app crashed mid-flush).
 */
export function useNetworkStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    // Recover stuck items once on mount
    syncEngine.recoverStuck().catch(() => {/* non-fatal */})

    const handleOffline = () => {
      setOnline(false)
      // AppLayout already shows the amber offline banner — no separate toast needed.
      toast.dismiss('offline-status')
    }

    const handleOnline = async () => {
      setOnline(true)
      toast.dismiss('offline-status')

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
          toast.success('Back online — reconnected.', { id: 'offline-reauth', duration: 3000 })
          await flushQueuedMutations()
        } else {
          toast('Back online — sign in when ready to sync your offline changes.', {
            id: 'offline-reauth',
            icon: '🔌',
            duration: 6000,
          })
        }
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
        toast.success('Back online', { duration: 2500 })
        return
      }
      await flushQueuedMutations()
    }

    window.addEventListener('offline', handleOffline)
    window.addEventListener('online', handleOnline)
    return () => {
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('online', handleOnline)
    }
  }, [])

  return online
}
