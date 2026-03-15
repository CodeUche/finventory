import { useRef, useState } from 'react'
import { Bell, X, Package, ChevronRight, AlertCircle, CalendarClock, Receipt, Users } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications } from '@/contexts/NotificationsContext'
import { formatCurrency, formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'

export default function NotificationBell() {
  const {
    alerts, overdueAlerts, expiryAlerts, billDueAlerts, payrollPendingAlerts,
    count, dismiss, dismissAll, dismissOverdue, dismissExpiry, dismissBillDue, dismissPayrollPending,
  } = useNotifications()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  const go = (path: string) => { setOpen(false); navigate(path) }

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
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />

          <div className="absolute right-0 top-full mt-2 w-80 bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl z-50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
              <span className="text-sm font-semibold text-white">
                Notifications {count > 0 && <span className="text-brand-400">({count})</span>}
              </span>
              {count > 0 && (
                <button onClick={dismissAll} className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
                  Clear all
                </button>
              )}
            </div>

            <div className="max-h-[480px] overflow-y-auto">
              {count === 0 ? (
                <div className="py-8 text-center">
                  <Bell size={24} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-sm text-slate-500">No alerts right now</p>
                </div>
              ) : (
                <>
                  {/* Bills due tomorrow */}
                  {billDueAlerts.length > 0 && (
                    <>
                      <button
                        onClick={() => go('/bills')}
                        className="w-full flex items-center gap-2 px-4 py-2.5 bg-purple-500/5 border-b border-surface-700 text-xs text-purple-400 hover:bg-purple-500/10 transition-colors"
                      >
                        <Receipt size={13} />
                        {billDueAlerts.length} bill{billDueAlerts.length > 1 ? 's' : ''} due tomorrow
                        <ChevronRight size={13} className="ml-auto" />
                      </button>
                      {billDueAlerts.map((b) => (
                        <div
                          key={b.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/bills')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-purple-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <Receipt size={13} className="text-purple-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">{b.bill_number} · {b.supplier_name}</p>
                            <p className="text-xs text-slate-500">{formatCurrency(b.amount_due)} due {formatDate(b.due_date)}</p>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissBillDue(b.id) }}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Payroll pending approval */}
                  {payrollPendingAlerts.length > 0 && (
                    <>
                      <button
                        onClick={() => go('/payroll')}
                        className="w-full flex items-center gap-2 px-4 py-2.5 bg-blue-500/5 border-b border-surface-700 text-xs text-blue-400 hover:bg-blue-500/10 transition-colors"
                      >
                        <Users size={13} />
                        {payrollPendingAlerts.length} payroll run{payrollPendingAlerts.length > 1 ? 's' : ''} awaiting approval
                        <ChevronRight size={13} className="ml-auto" />
                      </button>
                      {payrollPendingAlerts.map((r) => (
                        <div
                          key={r.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/payroll')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <Users size={13} className="text-blue-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">{r.run_number}</p>
                            <p className="text-xs text-slate-500">
                              {r.period_year}/{String(r.period_month).padStart(2, '0')} · Net {formatCurrency(r.total_net)} · Pending approval
                            </p>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissPayrollPending(r.id) }}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Low Stock Section */}
                  {alerts.length > 0 && (
                    <>
                      <button
                        onClick={() => go('/inventory/stock?filter=low')}
                        className="w-full flex items-center gap-2 px-4 py-2.5 bg-yellow-500/5 border-b border-surface-700 text-xs text-yellow-400 hover:bg-yellow-500/10 transition-colors"
                      >
                        <Package size={13} />
                        {alerts.length} product{alerts.length > 1 ? 's' : ''} low on stock
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

                  {/* Overdue Invoices Section */}
                  {overdueAlerts.length > 0 && (
                    <>
                      <button
                        onClick={() => go('/sales?status=overdue')}
                        className="w-full flex items-center gap-2 px-4 py-2.5 bg-red-500/5 border-b border-surface-700 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                      >
                        <AlertCircle size={13} />
                        {overdueAlerts.length} overdue invoice{overdueAlerts.length > 1 ? 's' : ''}
                        <ChevronRight size={13} className="ml-auto" />
                      </button>
                      {overdueAlerts.map((inv) => (
                        <div
                          key={inv.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/sales?status=overdue')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-red-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <AlertCircle size={13} className="text-red-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">
                              {inv.invoice_number} · {inv.customer_name ?? 'Walk-in'}
                            </p>
                            <p className="text-xs text-slate-500">
                              {formatCurrency(inv.amount_due)} · {inv.days_overdue}d overdue
                            </p>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissOverdue(inv.id) }}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Batch Expiry Section */}
                  {expiryAlerts.length > 0 && (
                    <>
                      <button
                        onClick={() => go('/inventory/batches')}
                        className="w-full flex items-center gap-2 px-4 py-2.5 bg-orange-500/5 border-b border-surface-700 text-xs text-orange-400 hover:bg-orange-500/10 transition-colors"
                      >
                        <CalendarClock size={13} />
                        {expiryAlerts.filter((a) => a.is_expired).length > 0
                          ? `${expiryAlerts.filter((a) => a.is_expired).length} expired`
                          : ''}{expiryAlerts.filter((a) => !a.is_expired).length > 0
                          ? ` ${expiryAlerts.filter((a) => !a.is_expired).length} expiring soon`
                          : ''} batch{expiryAlerts.length > 1 ? 'es' : ''}
                        <ChevronRight size={13} className="ml-auto" />
                      </button>
                      {expiryAlerts.slice(0, 5).map((b) => (
                        <div
                          key={b.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors"
                        >
                          <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${b.is_expired ? 'bg-red-500/10' : 'bg-orange-500/10'}`}>
                            <CalendarClock size={13} className={b.is_expired ? 'text-red-400' : 'text-orange-400'} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">{b.product_name}</p>
                            <p className="text-xs text-slate-500">
                              Batch {b.batch_number} · {b.is_expired
                                ? `Expired ${Math.abs(b.days_to_expiry ?? 0)}d ago`
                                : `Expires in ${b.days_to_expiry}d (${formatDate(b.expiry_date)})`}
                            </p>
                          </div>
                          <button
                            onClick={() => dismissExpiry(b.id)}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </div>

            {count > 0 && (
              <div className="flex flex-wrap border-t border-surface-700">
                {billDueAlerts.length > 0 && (
                  <button onClick={() => go('/bills')} className="flex-1 px-3 py-2.5 text-xs text-purple-400 hover:text-purple-300 font-medium text-center hover:bg-surface-700/30 transition-colors">
                    Bills →
                  </button>
                )}
                {payrollPendingAlerts.length > 0 && (
                  <button onClick={() => go('/payroll')} className="flex-1 px-3 py-2.5 text-xs text-blue-400 hover:text-blue-300 font-medium text-center hover:bg-surface-700/30 transition-colors border-l border-surface-700">
                    Payroll →
                  </button>
                )}
                {alerts.length > 0 && (
                  <button onClick={() => go('/inventory/stock?filter=low')} className="flex-1 px-3 py-2.5 text-xs text-yellow-400 hover:text-yellow-300 font-medium text-center hover:bg-surface-700/30 transition-colors border-l border-surface-700">
                    Stock →
                  </button>
                )}
                {overdueAlerts.length > 0 && (
                  <button onClick={() => go('/sales?status=overdue')} className="flex-1 px-3 py-2.5 text-xs text-red-400 hover:text-red-300 font-medium text-center hover:bg-surface-700/30 transition-colors border-l border-surface-700">
                    Overdue →
                  </button>
                )}
                {expiryAlerts.length > 0 && (
                  <button onClick={() => go('/inventory/batches')} className="flex-1 px-3 py-2.5 text-xs text-orange-400 hover:text-orange-300 font-medium text-center hover:bg-surface-700/30 transition-colors border-l border-surface-700">
                    Batches →
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
