import { useRef, useState } from 'react'
import { Bell, X, Package, ChevronRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications } from '@/contexts/NotificationsContext'
import { cn } from '@/lib/utils'

export default function NotificationBell() {
  const { alerts, count, dismiss, dismissAll } = useNotifications()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  const handleClickAlert = () => {
    setOpen(false)
    navigate('/inventory/stock?filter=low')
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn('btn-ghost relative p-2', open && 'bg-surface-700')}
      >
        <Bell size={18} />
        {count > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-0.5 bg-brand-500 rounded-full text-[10px] font-bold text-white flex items-center justify-center leading-none">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />

          {/* Dropdown */}
          <div className="absolute right-0 top-full mt-2 w-80 bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl z-50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
              <span className="text-sm font-semibold text-white">
                Notifications {count > 0 && <span className="text-brand-400">({count})</span>}
              </span>
              {count > 0 && (
                <button
                  onClick={dismissAll}
                  className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                >
                  Clear all
                </button>
              )}
            </div>

            <div className="max-h-80 overflow-y-auto">
              {count === 0 ? (
                <div className="py-8 text-center">
                  <Bell size={24} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-sm text-slate-500">No alerts right now</p>
                </div>
              ) : (
                <>
                  <button
                    onClick={handleClickAlert}
                    className="w-full flex items-center gap-2 px-4 py-2.5 bg-yellow-500/5 border-b border-surface-700 text-xs text-yellow-400 hover:bg-yellow-500/10 transition-colors"
                  >
                    <Package size={13} />
                    {count} product{count > 1 ? 's' : ''} low on stock
                    <ChevronRight size={13} className="ml-auto" />
                  </button>

                  {alerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors"
                    >
                      <div className="w-7 h-7 rounded-lg bg-yellow-500/10 flex items-center justify-center shrink-0 mt-0.5">
                        <Package size={13} className="text-yellow-400" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white truncate">{alert.product_name}</p>
                        <p className="text-xs text-slate-500">
                          {alert.warehouse_name} · {alert.quantity_available} left
                        </p>
                      </div>
                      <button
                        onClick={() => dismiss(alert.id)}
                        className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </>
              )}
            </div>

            {count > 0 && (
              <button
                onClick={handleClickAlert}
                className="w-full px-4 py-3 text-xs text-brand-400 hover:text-brand-300 font-medium text-center border-t border-surface-700 hover:bg-surface-700/30 transition-colors"
              >
                View all low-stock items →
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}
