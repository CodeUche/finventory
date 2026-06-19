import { useRef, useState } from 'react'
import { Bell, X, Package, AlertCircle, CalendarClock, Receipt, Users, Clock, ShieldCheck, Truck, CheckCircle2, CheckCircle, XCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useNotifications, EtaAlert, CustomerOutstandingAlert } from '@/contexts/NotificationsContext'
import { orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { formatCurrency, formatDate } from '@/lib/utils'
import { cn } from '@/lib/utils'
import toast from 'react-hot-toast'

export default function NotificationBell() {
  const {
    alerts, overdueAlerts, expiryAlerts, billDueAlerts, payrollPendingAlerts, customerDueAlerts,
    customerOutstandingAlerts, partnerRequestAlerts, etaAlerts,
    count, dismiss, dismissAll, dismissOverdue, dismissExpiry, dismissBillDue, dismissPayrollPending,
    dismissCustomerDue, dismissCustomerOutstanding, dismissPartnerRequest, dismissEta, quickReceive,
  } = useNotifications()
  const [open, setOpen] = useState(false)
  const [receivingId, setReceivingId] = useState<string | null>(null)
  const [partnerActionId, setPartnerActionId] = useState<string | null>(null)
  const { organisation } = useAuthStore()
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)

  const handleQuickReceive = async (id: string) => {
    setReceivingId(id)
    await quickReceive(id)
    setReceivingId(null)
  }

  const handleApprovePartner = async (alertId: string) => {
    if (!organisation?.id) return
    const reqId = alertId.replace(/^pr-/, '')
    setPartnerActionId(alertId)
    try {
      await orgApi.approvePartnerRequest(organisation.id, reqId)
      dismissPartnerRequest(alertId)
      toast.success('Accountant access approved')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to approve')
    } finally {
      setPartnerActionId(null)
    }
  }

  const handleRejectPartner = async (alertId: string) => {
    if (!organisation?.id) return
    const reqId = alertId.replace(/^pr-/, '')
    setPartnerActionId(alertId)
    try {
      await orgApi.rejectPartnerRequest(organisation.id, reqId, '')
      dismissPartnerRequest(alertId)
      toast.success('Request rejected')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to reject')
    } finally {
      setPartnerActionId(null)
    }
  }

  const go = (path: string) => { setOpen(false); navigate(path) }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn('btn-ghost relative p-2 text-slate-300 hover:text-white', open && 'bg-surface-700')}
      >
        <Bell size={18} />
        {count > 0 && (
          <span className="absolute top-1 right-1 min-w-[16px] h-4 px-0.5 bg-red-500 rounded-full text-[10px] font-bold text-always-white flex items-center justify-center leading-none">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-[199]" onClick={() => setOpen(false)} />

          <div className="absolute right-0 top-full mt-2 w-80 bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl z-[200] overflow-hidden">
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
                  {/* Partner access requests */}
                  {partnerRequestAlerts.length > 0 && (
                    <>
                      {partnerRequestAlerts.map((req) => (
                        <div
                          key={req.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/settings?tab=access')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <ShieldCheck size={13} className="text-amber-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">
                              Accountant access request
                            </p>
                            <p className="text-xs text-slate-500 truncate">
                              {req.partner_firm_name || req.partner_email} wants access to your books
                            </p>
                            <div className="flex gap-1.5 mt-1.5" onClick={(e) => e.stopPropagation()}>
                              <button
                                disabled={partnerActionId === req.id}
                                onClick={() => handleApprovePartner(req.id)}
                                className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-green-500/20 text-green-400 hover:bg-green-500/30 disabled:opacity-50 transition-colors"
                              >
                                <CheckCircle size={10} /> Approve
                              </button>
                              <button
                                disabled={partnerActionId === req.id}
                                onClick={() => handleRejectPartner(req.id)}
                                className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 transition-colors"
                              >
                                <XCircle size={10} /> Reject
                              </button>
                            </div>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissPartnerRequest(req.id) }}
                            className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ))}
                    </>
                  )}

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

                  {/* Customers with an outstanding balance yet to pay */}
                  {customerOutstandingAlerts.length > 0 && (
                    <>
                      {customerOutstandingAlerts.map((c: CustomerOutstandingAlert) => (
                        <div
                          key={c.id}
                          className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                          onClick={() => go('/customers')}
                        >
                          <div className="w-7 h-7 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0 mt-0.5">
                            <Users size={13} className="text-amber-400" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-white truncate">{c.customer_name}</p>
                            <p className="text-xs text-slate-500">{formatCurrency(c.outstanding_balance)} outstanding</p>
                          </div>
                          <button
                            onClick={(e) => { e.stopPropagation(); dismissCustomerOutstanding(c.id) }}
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

                  {/* PO ETA / Delivery Alerts */}
                  {etaAlerts.length > 0 && etaAlerts.map((eta: EtaAlert) => {
                    const isActionable = eta.tier === 'due_today' || eta.tier === 'overdue'
                    const tierColor = eta.tier === 'arriving_tomorrow'
                      ? { bg: 'bg-blue-500/10', icon: 'text-blue-400' }
                      : eta.tier === 'due_today'
                      ? { bg: 'bg-amber-500/10', icon: 'text-amber-400' }
                      : { bg: 'bg-red-500/10', icon: 'text-red-400' }
                    const tierLabel = eta.tier === 'arriving_tomorrow'
                      ? 'Expected tomorrow'
                      : eta.tier === 'due_today'
                      ? 'Due today'
                      : `Overdue by ${eta.days_overdue}d`
                    return (
                      <div
                        key={eta.id}
                        className="flex items-start gap-3 px-4 py-3 border-b border-surface-700/60 hover:bg-surface-700/30 transition-colors cursor-pointer"
                        onClick={() => go('/purchases')}
                      >
                        <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5 ${tierColor.bg}`}>
                          <Truck size={13} className={tierColor.icon} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium text-white truncate">
                            {eta.po_number} · {eta.supplier_name}
                          </p>
                          <p className="text-xs text-slate-500">
                            {tierLabel} · {eta.item_count} item{eta.item_count !== 1 ? 's' : ''} · {formatCurrency(eta.total_amount)}
                          </p>
                          {isActionable && (
                            <div className="flex gap-2 mt-1.5" onClick={(e) => e.stopPropagation()}>
                              <button
                                disabled={receivingId === eta.id}
                                onClick={() => handleQuickReceive(eta.id)}
                                className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 disabled:opacity-50 transition-colors"
                              >
                                <CheckCircle2 size={10} />
                                {receivingId === eta.id ? 'Receiving…' : 'Received'}
                              </button>
                              <button
                                onClick={() => dismissEta(eta.id)}
                                className="text-[11px] px-2 py-0.5 rounded-md bg-surface-600/50 text-slate-400 hover:bg-surface-600 transition-colors"
                              >
                                Not yet
                              </button>
                            </div>
                          )}
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); dismissEta(eta.id) }}
                          className="shrink-0 p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    )
                  })}

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
