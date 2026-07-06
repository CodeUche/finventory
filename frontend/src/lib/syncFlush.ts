/**
 * Shared "flush the offline queue" trigger with user-facing toasts.
 *
 * Called from every place a sync can become possible — not only the 'online'
 * event (the original bug: an offline grace session ended on reconnect BEFORE
 * the flush ran, and no later 'online' event ever fired, so queued sales sat
 * unsynced forever):
 *   • useNetworkStatus — connectivity restored with a real-token session
 *   • AppLayout mount  — right after any successful login (normal, MFA, staff)
 *   • AppLayout        — organisation switch (flush is org-scoped)
 *
 * Safe to call optimistically: no-ops when the queue is empty, when a flush
 * is already running (syncEngine guards), or when the session can't sync
 * (offline grace session / no tokens — flushing without tokens would 401
 * every item straight into 'conflict' state).
 */

import toast from 'react-hot-toast'
import { syncEngine } from '@/lib/syncEngine'
import { useAuthStore } from '@/store/authStore'

export async function flushQueuedMutations(): Promise<void> {
  const { tokens, isOfflineSession } = useAuthStore.getState()
  if (!tokens?.access || isOfflineSession) return
  if (!navigator.onLine) return

  const pending = await syncEngine.pendingCount()
  if (pending === 0) return

  const flushToast = toast.loading(`Syncing ${pending} queued operation${pending > 1 ? 's' : ''}…`)
  try {
    const { succeeded, conflicts } = await syncEngine.flush()
    toast.dismiss(flushToast)
    if (succeeded === 0 && conflicts === 0) return // another flush already ran, or network dropped again
    if (conflicts === 0) {
      toast.success(`Synced ${succeeded} operation${succeeded > 1 ? 's' : ''} successfully.`)
    } else {
      toast.error(`Sync complete — ${succeeded} succeeded, ${conflicts} conflict${conflicts > 1 ? 's' : ''} need attention.`, { duration: 6000 })
    }
  } catch {
    toast.dismiss(flushToast)
    toast.error('Sync failed — will retry when connection is stable.')
  }
}
