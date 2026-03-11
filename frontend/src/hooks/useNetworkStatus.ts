import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { offlineQueue } from '@/lib/offlineQueue'

/**
 * Returns `true` when the browser reports network connectivity.
 *
 * Side effects:
 * - Shows a toast banner when going offline or back online.
 * - On reconnect, flushes any queued mutations from the offline queue.
 */
export function useNetworkStatus(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    const handleOffline = () => {
      setOnline(false)
      toast.error('You are offline — changes will be queued and synced when reconnected.', {
        id: 'offline-status',
        duration: Infinity,
        icon: '📶',
      })
    }

    const handleOnline = async () => {
      setOnline(true)
      toast.dismiss('offline-status')

      const pending = offlineQueue.peek()
      if (pending.length === 0) {
        toast.success('Back online', { duration: 2500 })
        return
      }

      const flushToast = toast.loading(`Syncing ${pending.length} queued request${pending.length > 1 ? 's' : ''}…`)
      try {
        const { succeeded, failed } = await offlineQueue.flush()
        toast.dismiss(flushToast)
        if (failed === 0) {
          toast.success(`Synced ${succeeded} operation${succeeded > 1 ? 's' : ''} successfully.`)
        } else {
          toast.error(`Sync complete — ${succeeded} succeeded, ${failed} failed.`)
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
