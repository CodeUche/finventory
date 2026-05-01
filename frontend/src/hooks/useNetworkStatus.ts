import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { syncEngine } from '@/lib/syncEngine'

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

      const pending = await syncEngine.pendingCount()
      if (pending === 0) {
        toast.success('Back online', { duration: 2500 })
        return
      }

      const flushToast = toast.loading(`Syncing ${pending} queued operation${pending > 1 ? 's' : ''}…`)
      try {
        const { succeeded, conflicts } = await syncEngine.flush()
        toast.dismiss(flushToast)
        if (conflicts === 0) {
          toast.success(`Synced ${succeeded} operation${succeeded > 1 ? 's' : ''} successfully.`)
        } else {
          toast.error(`Sync complete — ${succeeded} succeeded, ${conflicts} conflict${conflicts > 1 ? 's' : ''} need attention.`, { duration: 6000 })
        }
      } catch {
        toast.dismiss(flushToast)
        toast.error('Sync failed — please refresh and try again.')
      }
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
