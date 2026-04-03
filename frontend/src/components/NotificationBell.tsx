import { useRef, useState } from 'react'
import { Bell, X, Package, AlertCircle, CalendarClock, Receipt, Users, Clock } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications } from '@/contexts/NotificationsContext'
import { formatCurrency, formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'

export default function NotificationBell() {
  const {
    alerts, overdueAlerts, expiryAlerts, billDueAlerts, payrollPendingAlerts, customerDueAlerts,
    count, dismiss, dismissAll, dismissOverdue, dismissExpiry, dismissBillDue, dismissPayrollPending, dismissCustomerDue,
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
                  {/* Customer payments due within 7 days */}
                  {customerDueAlerts.length > 0 && (
                    <>
                      {customerDueAlerts.map((inv) => (
                        <div
                          key={inv.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/sales')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <Clock size={13} className="text-cyan-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">
                              {inv.invoice_number} · {inv.customer_name ?? 'Walk-in'}
                            </p>
                            <p className="text-xs text-slate-500">
                              {formatCurrency(inv.amount_due)} · due {inv.days_until_due === 0 ? 'today' : `in ${inv.days_until_due}d`} ({formatDate(inv.due_date)})
                            </p>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissCustomerDue(inv.id) }}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}

                  {/* Bills due tomorrow */}
                  {billDueAlerts.length > 0 && (
                    <>
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
                      {payrollPendingAlerts.map((r) => (
                        <div
                          key={r.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/payroll/runs')}
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

          </div>
        </>
      )}
    </div>
  )
}
