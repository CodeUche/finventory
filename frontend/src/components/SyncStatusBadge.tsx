/**
 * SyncStatusBadge — shows sync queue status in the TopBar.
 *
 * States:
 *   • Hidden when queue is empty
 *   • Spinning loader + count when items are pending sync
 *   • Orange warning icon + count when there are conflicts needing attention
 *
 * Clicking opens a drawer listing all queued/conflicted operations
 * with per-item Retry and Dismiss buttons.
 */

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Loader2, RefreshCw, X, CheckCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { syncEngine, type SyncItem } from '@/lib/syncEngine'

function formatLabel(item: SyncItem): string {
  const method = item.method.toUpperCase()
  // Turn /api/v1/payroll/employees/ → Employees
  const urlPath = item.url.replace(/\/api\/v\d+\//, '').replace(/\/$/, '')
  const parts = urlPath.split('/').filter(Boolean)
  const resource = parts.find((p) => !/^[0-9a-f-]{36}$/.test(p) && p !== 'api' && !/^v\d+$/.test(p))
  const name = resource ? resource.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : urlPath
  const verb = method === 'POST' ? 'Create' : method === 'PUT' || method === 'PATCH' ? 'Update' : method === 'DELETE' ? 'Delete' : method
  return `${verb} ${name}`
}

function timeAgo(ms: number): string {
  const diff = Date.now() - ms
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.floor(minutes / 60)}h ago`
}

export function SyncStatusBadge() {
  const [items, setItems] = useState<SyncItem[]>([])
  const [open, setOpen] = useState(false)
  const drawerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Load initial state
    syncEngine.snapshot().then(setItems)
    // Subscribe to changes
    return syncEngine.subscribe(setItems)
  }, [])

  // Close drawer on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const pending = items.filter((i) => i.status === 'pending' || i.status === 'syncing')
  const conflicts = items.filter((i) => i.status === 'conflict')

  if (items.length === 0) return null

  const hasConflicts = conflicts.length > 0
  const count = hasConflicts ? conflicts.length : pending.length

  return (
    <div className="relative" ref={drawerRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={`relative flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-xs font-medium transition-colors ${
          hasConflicts
            ? 'bg-orange-500/20 text-orange-400 hover:bg-orange-500/30'
            : 'bg-brand-500/20 text-brand-400 hover:bg-brand-500/30'
        }`}
        title={hasConflicts ? `${conflicts.length} sync conflict${conflicts.length > 1 ? 's' : ''} — click to review` : `${pending.length} operation${pending.length > 1 ? 's' : ''} queued for sync`}
      >
        {hasConflicts ? (
          <AlertTriangle size={13} />
        ) : (
          <Loader2 size={13} className="animate-spin" />
        )}
        <span>{count}</span>
        {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-surface-800 border border-surface-700 rounded-xl shadow-2xl z-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
            <div>
              <p className="text-sm font-semibold text-white">Sync Queue</p>
              <p className="text-xs text-slate-400">
                {pending.length > 0 && `${pending.length} pending`}
                {pending.length > 0 && conflicts.length > 0 && ' · '}
                {conflicts.length > 0 && (
                  <span className="text-orange-400">{conflicts.length} conflict{conflicts.length > 1 ? 's' : ''}</span>
                )}
              </p>
            </div>
            <button onClick={() => setOpen(false)} className="text-slate-500 hover:text-white">
              <X size={15} />
            </button>
          </div>

          {/* Item list */}
          <div className="max-h-72 overflow-y-auto">
            {items.length === 0 && (
              <div className="flex flex-col items-center gap-2 py-8 text-slate-500">
                <CheckCircle size={20} />
                <p className="text-xs">All synced</p>
              </div>
            )}
            {items.map((item) => (
              <div key={item.id} className={`flex items-start gap-3 px-4 py-3 border-b border-surface-700/50 last:border-0 ${item.status === 'conflict' ? 'bg-orange-500/5' : ''}`}>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white truncate">{formatLabel(item)}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{timeAgo(item.timestamp)}</p>
                  {item.lastError && (
                    <p className="text-xs text-orange-400 mt-0.5 truncate" title={item.lastError}>
                      {item.lastError}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0 mt-0.5">
                  {item.status === 'conflict' && (
                    <button
                      onClick={() => syncEngine.retry(item.id)}
                      className="p-1 rounded hover:bg-surface-700 text-brand-400 hover:text-brand-300"
                      title="Retry"
                    >
                      <RefreshCw size={13} />
                    </button>
                  )}
                  <button
                    onClick={() => syncEngine.dismiss(item.id)}
                    className="p-1 rounded hover:bg-surface-700 text-slate-500 hover:text-white"
                    title="Dismiss"
                  >
                    <X size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Footer */}
          {conflicts.length > 0 && (
            <div className="px-4 py-3 border-t border-surface-700 flex items-center justify-between">
              <p className="text-xs text-slate-400">Conflicts won't be retried automatically</p>
              <button
                onClick={async () => {
                  for (const c of conflicts) await syncEngine.dismiss(c.id)
                }}
                className="text-xs text-orange-400 hover:text-orange-300"
              >
                Dismiss all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
