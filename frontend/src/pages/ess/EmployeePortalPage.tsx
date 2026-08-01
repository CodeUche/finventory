import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Banknote, Briefcase, CalendarDays, FileText, Loader2, LogOut, Plus,
  ShieldCheck, User as UserIcon, Wallet, X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import DateInput from '@/components/DateInput'
import { confirmDialog } from '@/lib/dialog'
import { essApi } from '@/services/api'
import { formatCurrency, formatDate, setActiveCurrency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import type {
  AdvanceRequest, EmployeeBenefit, EmployeeDocument, EssSummary,
  LeaveBalance, LeaveRequest, LeaveType, PayslipLine,
} from '@/types'

type Tab = 'overview' | 'payslips' | 'leave' | 'benefits' | 'documents' | 'advances'

const TABS: { key: Tab; label: string; icon: typeof UserIcon }[] = [
  { key: 'overview', label: 'Overview', icon: UserIcon },
  { key: 'payslips', label: 'Payslips', icon: FileText },
  { key: 'leave', label: 'Leave', icon: CalendarDays },
  { key: 'benefits', label: 'Benefits', icon: Briefcase },
  { key: 'documents', label: 'Documents', icon: FileText },
  { key: 'advances', label: 'Advances', icon: Wallet },
]

const MONTHS = [
  '', 'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-400',
  approved: 'bg-emerald-500/15 text-emerald-400',
  disbursed: 'bg-emerald-500/15 text-emerald-400',
  recovered: 'bg-sky-500/15 text-sky-400',
  rejected: 'bg-red-500/15 text-red-400',
  cancelled: 'bg-slate-500/15 text-slate-400',
}

type PayslipRow = PayslipLine & {
  period_year: number
  period_month: number
  run_number: string
  run_status: string
  payment_date: string | null
}

const today = new Date().toISOString().split('T')[0]

/**
 * Employee self-service portal.
 *
 * Rendered on its own shell — an employee never sees the operator sidebar. All
 * data is resolved server-side from the signed-in user's linked Employee record,
 * so no employee id is ever sent from here.
 */
export default function EmployeePortalPage() {
  const logout = useAuthStore((s) => s.logout)

  const [tab, setTab] = useState<Tab>('overview')
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<EssSummary | null>(null)

  const [payslips, setPayslips] = useState<PayslipRow[]>([])
  const [leaveRequests, setLeaveRequests] = useState<LeaveRequest[]>([])
  const [leaveBalances, setLeaveBalances] = useState<LeaveBalance[]>([])
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([])
  const [benefits, setBenefits] = useState<EmployeeBenefit[]>([])
  const [documents, setDocuments] = useState<EmployeeDocument[]>([])
  const [advances, setAdvances] = useState<AdvanceRequest[]>([])

  const [showLeave, setShowLeave] = useState(false)
  const [leaveForm, setLeaveForm] = useState({
    leave_type: '', start_date: today, end_date: today, reason: '',
  })
  const [showAdvance, setShowAdvance] = useState(false)
  const [advanceAmount, setAdvanceAmount] = useState('')
  const [saving, setSaving] = useState(false)
  const [viewSlip, setViewSlip] = useState<PayslipRow | null>(null)

  const unwrap = <T,>(d: unknown): T[] =>
    (Array.isArray(d) ? d : ((d as { results?: T[] })?.results ?? [])) as T[]

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await essApi.summary()
      setSummary(res.data)
      if (res.data?.organisation?.currency) setActiveCurrency(res.data.organisation.currency)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        toast.error('This account is not linked to an employee record.')
      } else {
        toast.error('Could not load your portal')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const loadTab = useCallback(async (next: Tab) => {
    try {
      if (next === 'payslips' && payslips.length === 0) {
        const res = await essApi.payslips()
        setPayslips(unwrap<PayslipRow>(res.data))
      }
      if (next === 'leave') {
        const [reqRes, balRes, typeRes] = await Promise.all([
          essApi.leaveRequests(), essApi.leaveBalances(), essApi.leaveTypes(),
        ])
        setLeaveRequests(unwrap<LeaveRequest>(reqRes.data))
        setLeaveBalances(unwrap<LeaveBalance>(balRes.data))
        setLeaveTypes(unwrap<LeaveType>(typeRes.data))
      }
      if (next === 'benefits' && benefits.length === 0) {
        const res = await essApi.benefits()
        setBenefits(unwrap<EmployeeBenefit>(res.data))
      }
      if (next === 'documents' && documents.length === 0) {
        const res = await essApi.documents()
        setDocuments(unwrap<EmployeeDocument>(res.data))
      }
      if (next === 'advances') {
        const res = await essApi.advances()
        setAdvances(unwrap<AdvanceRequest>(res.data))
      }
    } catch {
      toast.error('Could not load that section')
    }
  }, [payslips.length, benefits.length, documents.length])

  function switchTab(next: Tab) {
    setTab(next)
    void loadTab(next)
  }

  const advance = summary?.advance ?? null
  const advanceAvailable = parseFloat(advance?.available ?? '0')
  const accruedNet = parseFloat(advance?.accrued_net ?? '0')
  const advancePct = accruedNet > 0
    ? Math.min(100, Math.max(0, (advanceAvailable / accruedNet) * 100))
    : 0

  const primaryLeave = useMemo(
    () => (summary?.leave_balances ?? []).find((b) => parseFloat(b.entitled_days) > 0)
      ?? summary?.leave_balances?.[0]
      ?? null,
    [summary],
  )

  async function submitLeave(e: React.FormEvent) {
    e.preventDefault()
    if (!leaveForm.leave_type) {
      toast.error('Choose a leave type')
      return
    }
    setSaving(true)
    try {
      await essApi.createLeaveRequest(leaveForm)
      toast.success('Leave request submitted for approval')
      setShowLeave(false)
      setLeaveForm({ leave_type: '', start_date: today, end_date: today, reason: '' })
      await Promise.all([load(), loadTab('leave')])
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not submit the request')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  async function cancelLeave(req: LeaveRequest) {
    const ok = await confirmDialog(
      `Cancel this request? ${req.days} day(s) of ${req.leave_type_name}.`,
      { confirmText: 'Cancel request' },
    )
    if (!ok) return
    try {
      await essApi.cancelLeaveRequest(req.id)
      toast.success('Request cancelled')
      await loadTab('leave')
    } catch {
      toast.error('Could not cancel the request')
    }
  }

  async function submitAdvance(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      await essApi.requestAdvance({ amount: advanceAmount })
      toast.success('Advance requested')
      setShowAdvance(false)
      setAdvanceAmount('')
      await Promise.all([load(), loadTab('advances')])
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not request an advance')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface-950">
        <Loader2 className="w-7 h-7 animate-spin text-brand-400" />
      </div>
    )
  }

  if (!summary) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-surface-950 p-6 text-center">
        <ShieldCheck className="w-10 h-10 text-slate-500" />
        <div>
          <p className="text-white font-semibold">No employee record linked</p>
          <p className="text-sm text-slate-400 mt-1 max-w-sm">
            This login is not connected to an employee. Ask your administrator to invite you
            from the HR module.
          </p>
        </div>
        <button onClick={() => logout()} className="btn-secondary">Sign out</button>
      </div>
    )
  }

  const emp = summary.employee
  const slip = summary.latest_payslip

  return (
    <div className="min-h-screen bg-surface-950">
      <header className="border-b border-white/10 bg-surface-900/60 backdrop-blur">
        <div className="max-w-5xl mx-auto px-4 py-3 flex flex-wrap items-center gap-3">
          <div>
            <p className="text-lg font-bold text-white">Hello, {emp.first_name}</p>
            <p className="text-xs text-slate-400 font-mono">
              {emp.department || emp.job_title} · {emp.employee_id} · {summary.organisation.name}
            </p>
          </div>
          <button onClick={() => logout()} className="ml-auto btn-secondary flex items-center gap-1.5 text-xs">
            <LogOut className="w-4 h-4" /> Sign out
          </button>
        </div>
        <div className="max-w-5xl mx-auto px-4 flex gap-1 overflow-x-auto">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => switchTab(t.key)}
              className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors flex items-center gap-1.5 ${
                tab === t.key
                  ? 'border-brand-500 text-brand-400 font-semibold'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <t.icon className="w-4 h-4" />
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-4">
        {tab === 'overview' && (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="card p-4 space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-[10px] uppercase tracking-wider text-slate-400">Latest payslip</p>
                {slip && (
                  <span className="ml-auto text-[10px] px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                    {slip.run_status === 'paid' ? `Paid ${formatDate(slip.payment_date ?? '')}` : slip.run_status}
                  </span>
                )}
              </div>
              {!slip ? (
                <p className="text-sm text-slate-400 py-6 text-center">No payslip issued yet.</p>
              ) : (
                <>
                  <p className="text-xs text-slate-400 font-mono">
                    {MONTHS[slip.period_month]} {slip.period_year}
                  </p>
                  <table className="w-full text-sm">
                    <tbody>
                      <tr><td className="py-1 text-slate-300">Gross</td>
                        <td className="py-1 text-right font-mono text-slate-100">{formatCurrency(slip.gross_salary)}</td></tr>
                      <tr><td className="py-1 text-slate-300">Pension 8%</td>
                        <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.employee_pension)}</td></tr>
                      {parseFloat(slip.nhf || '0') > 0 && (
                        <tr><td className="py-1 text-slate-300">NHF 2.5%</td>
                          <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.nhf)}</td></tr>
                      )}
                      {parseFloat(slip.benefit_deductions || '0') > 0 && (
                        <tr><td className="py-1 text-slate-300">Benefits</td>
                          <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.benefit_deductions ?? 0)}</td></tr>
                      )}
                      <tr><td className="py-1 text-slate-300">
                        PAYE{slip.tax_authority_name ? ` · ${slip.tax_authority_name}` : ''}
                      </td>
                        <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.paye_tax)}</td></tr>
                      {parseFloat(slip.loan_deductions || '0') > 0 && (
                        <tr><td className="py-1 text-slate-300">Loan repayment</td>
                          <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.loan_deductions)}</td></tr>
                      )}
                      {parseFloat(slip.advance_deductions || '0') > 0 && (
                        <tr><td className="py-1 text-slate-300">Salary advance</td>
                          <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(slip.advance_deductions ?? 0)}</td></tr>
                      )}
                      <tr className="border-t border-white/10">
                        <td className="py-2 text-white font-semibold">Net paid</td>
                        <td className="py-2 text-right font-mono text-emerald-400 font-bold">
                          {formatCurrency(slip.net_salary)}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <button
                    onClick={() => { switchTab('payslips') }}
                    className="btn-secondary w-full text-xs"
                  >
                    All payslips
                  </button>
                </>
              )}
            </div>

            <div className="space-y-4">
              <div className="card p-4 space-y-2">
                <div className="flex items-center gap-2">
                  <p className="text-[10px] uppercase tracking-wider text-slate-400">Leave balance</p>
                  {summary.open_leave_requests > 0 && (
                    <span className="ml-auto text-[10px] px-2 py-0.5 rounded bg-sky-500/15 text-sky-400">
                      {summary.open_leave_requests} open
                    </span>
                  )}
                </div>
                {primaryLeave ? (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span className="text-2xl font-bold text-white font-mono">
                        {primaryLeave.available_days}
                      </span>
                      <span className="text-xs text-slate-400">
                        days available of {primaryLeave.entitled_days} · {primaryLeave.leave_type_name}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-sky-400"
                        style={{
                          width: `${Math.min(100, Math.max(0,
                            (parseFloat(primaryLeave.available_days) /
                              (parseFloat(primaryLeave.entitled_days) || 1)) * 100))}%`,
                        }}
                      />
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-slate-400">No leave entitlement recorded yet.</p>
                )}
                <button onClick={() => { switchTab('leave'); setShowLeave(true) }} className="btn-secondary w-full text-xs">
                  Request leave
                </button>
              </div>

              {advance && (
                <div className="card p-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <p className="text-[10px] uppercase tracking-wider text-slate-400">Salary advance</p>
                    <span className={`ml-auto text-[10px] px-2 py-0.5 rounded ${
                      advance.eligible ? 'bg-emerald-500/15 text-emerald-400' : 'bg-slate-500/15 text-slate-400'
                    }`}>
                      {advance.eligible ? 'Eligible' : 'Not available'}
                    </span>
                  </div>
                  <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-bold text-brand-400 font-mono">
                      {formatCurrency(advance.available)}
                    </span>
                    <span className="text-xs text-slate-400">
                      of {formatCurrency(advance.accrued_net)} earned so far
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                    <div className="h-full rounded-full bg-brand-500" style={{ width: `${advancePct}%` }} />
                  </div>
                  <p className="text-[10px] text-slate-500 font-mono leading-relaxed">
                    {advance.days_worked} of {advance.days_in_period} working days ·
                    capped at {advance.max_percent_of_accrued}% of accrued net ·
                    recovered from this month&rsquo;s pay
                  </p>
                  {advance.eligible ? (
                    <button
                      onClick={() => { switchTab('advances'); setShowAdvance(true) }}
                      className="btn-primary w-full text-xs"
                    >
                      Request advance
                    </button>
                  ) : (
                    advance.reasons.length > 0 && (
                      <p className="text-[11px] text-slate-500">{advance.reasons[0]}</p>
                    )
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'payslips' && (
          <div className="card overflow-hidden">
            {payslips.length === 0 ? (
              <p className="p-10 text-center text-sm text-slate-400">No payslips yet.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-white/[0.03]">
                    <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                      <th className="px-4 py-3">Period</th>
                      <th className="px-4 py-3 text-right">Gross</th>
                      <th className="px-4 py-3 text-right">PAYE</th>
                      <th className="px-4 py-3 text-right">Net</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {payslips.map((p) => (
                      <tr key={p.id} className="border-t border-white/5">
                        <td className="px-4 py-3 text-white">
                          {MONTHS[p.period_month]} {p.period_year}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-slate-300">
                          {formatCurrency(p.gross_salary)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-slate-400">
                          {formatCurrency(p.paye_tax)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-emerald-400 font-semibold">
                          {formatCurrency(p.net_salary)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button onClick={() => setViewSlip(p)} className="text-xs text-brand-400 hover:underline">
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {tab === 'leave' && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <p className="text-sm text-slate-400">Your leave</p>
              <button onClick={() => setShowLeave(true)} className="ml-auto btn-primary text-xs flex items-center gap-1.5">
                <Plus className="w-4 h-4" /> Request leave
              </button>
            </div>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {leaveBalances.map((b) => (
                <div key={b.id} className="card p-3 space-y-1.5">
                  <p className="text-xs text-slate-300">{b.leave_type_name}</p>
                  <p className="text-lg font-bold text-white font-mono">{b.available_days}</p>
                  <p className="text-[10px] text-slate-500 font-mono">
                    entitled {b.entitled_days} · taken {b.taken_days} · pending {b.pending_days}
                  </p>
                </div>
              ))}
            </div>

            <div className="card overflow-hidden">
              {leaveRequests.length === 0 ? (
                <p className="p-8 text-center text-sm text-slate-400">No requests yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-white/[0.03]">
                    <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Dates</th>
                      <th className="px-4 py-3 text-right">Days</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaveRequests.map((r) => (
                      <tr key={r.id} className="border-t border-white/5">
                        <td className="px-4 py-3 text-white">{r.leave_type_name}</td>
                        <td className="px-4 py-3 text-slate-300 text-xs whitespace-nowrap">
                          {formatDate(r.start_date)} – {formatDate(r.end_date)}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-slate-200">{r.days}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded capitalize ${STATUS_STYLE[r.status] ?? ''}`}>
                            {r.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {(r.status === 'pending' || r.status === 'approved') && (
                            <button onClick={() => cancelLeave(r)} className="text-xs text-slate-400 hover:text-red-400">
                              Cancel
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {tab === 'benefits' && (
          <div className="card overflow-hidden">
            {benefits.length === 0 ? (
              <p className="p-10 text-center text-sm text-slate-400">You are not enrolled in any benefits.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-white/[0.03]">
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                    <th className="px-4 py-3">Plan</th>
                    <th className="px-4 py-3">Provider</th>
                    <th className="px-4 py-3">Tier</th>
                    <th className="px-4 py-3">Since</th>
                  </tr>
                </thead>
                <tbody>
                  {benefits.map((b) => (
                    <tr key={b.id} className="border-t border-white/5">
                      <td className="px-4 py-3 text-white">{b.plan_name}</td>
                      <td className="px-4 py-3 text-slate-300">{b.provider_name}</td>
                      <td className="px-4 py-3 text-slate-300">{b.tier || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{formatDate(b.start_date)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === 'documents' && (
          <div className="card overflow-hidden">
            {documents.length === 0 ? (
              <p className="p-10 text-center text-sm text-slate-400">No documents on file.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-white/[0.03]">
                  <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Size</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((d) => (
                    <tr key={d.id} className="border-t border-white/5">
                      <td className="px-4 py-3 text-white">{d.name}</td>
                      <td className="px-4 py-3 text-slate-300 capitalize">{d.document_type}</td>
                      <td className="px-4 py-3 text-slate-400 font-mono text-xs">{d.file_size_display}</td>
                      <td className="px-4 py-3 text-right">
                        {d.file_url && (
                          <a href={d.file_url} target="_blank" rel="noreferrer" className="text-xs text-brand-400 hover:underline">
                            Open
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {tab === 'advances' && (
          <div className="space-y-4">
            {advance && (
              <div className="card p-4 space-y-2">
                <p className="text-[10px] uppercase tracking-wider text-slate-400">Available now</p>
                <div className="flex items-baseline gap-2">
                  <span className="text-2xl font-bold text-brand-400 font-mono">
                    {formatCurrency(advance.available)}
                  </span>
                  <span className="text-xs text-slate-400">
                    of {formatCurrency(advance.accrued_net)} earned this period
                  </span>
                  {advance.eligible && (
                    <button
                      onClick={() => setShowAdvance(true)}
                      className="ml-auto btn-primary text-xs flex items-center gap-1.5"
                    >
                      <Banknote className="w-4 h-4" /> Request
                    </button>
                  )}
                </div>
                {!advance.eligible && advance.reasons.length > 0 && (
                  <ul className="text-[11px] text-slate-500 list-disc pl-4 space-y-0.5">
                    {advance.reasons.map((r) => <li key={r}>{r}</li>)}
                  </ul>
                )}
              </div>
            )}

            <div className="card overflow-hidden">
              {advances.length === 0 ? (
                <p className="p-8 text-center text-sm text-slate-400">No advances requested.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-white/[0.03]">
                    <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                      <th className="px-4 py-3">Period</th>
                      <th className="px-4 py-3 text-right">Amount</th>
                      <th className="px-4 py-3 text-right">Fee</th>
                      <th className="px-4 py-3 text-right">To repay</th>
                      <th className="px-4 py-3">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {advances.map((a) => (
                      <tr key={a.id} className="border-t border-white/5">
                        <td className="px-4 py-3 text-white">
                          {MONTHS[a.period_month]} {a.period_year}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-slate-200">{formatCurrency(a.amount)}</td>
                        <td className="px-4 py-3 text-right font-mono text-slate-400">{formatCurrency(a.fee)}</td>
                        <td className="px-4 py-3 text-right font-mono text-slate-100">{formatCurrency(a.total_recoverable)}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded capitalize ${STATUS_STYLE[a.status] ?? ''}`}>
                            {a.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </main>

      {showLeave && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={submitLeave} className="card w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Request leave</h2>
              <button type="button" onClick={() => setShowLeave(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Type</label>
              <select
                className="input"
                value={leaveForm.leave_type}
                onChange={(e) => setLeaveForm({ ...leaveForm, leave_type: e.target.value })}
                required
              >
                <option value="">Select…</option>
                {leaveTypes.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}{t.is_paid ? '' : ' (unpaid)'}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">From</label>
                <DateInput value={leaveForm.start_date} onChange={(v) => setLeaveForm({ ...leaveForm, start_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">To</label>
                <DateInput value={leaveForm.end_date} onChange={(v) => setLeaveForm({ ...leaveForm, end_date: v })} />
              </div>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Reason</label>
              <input
                className="input"
                value={leaveForm.reason}
                onChange={(e) => setLeaveForm({ ...leaveForm, reason: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowLeave(false)} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
                {saving && <Loader2 className="w-4 h-4 animate-spin" />} Submit
              </button>
            </div>
          </form>
        </div>
      )}

      {showAdvance && advance && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={submitAdvance} className="card w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Request a salary advance</h2>
              <button type="button" onClick={() => setShowAdvance(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="rounded-lg bg-white/[0.03] border border-white/5 p-3 text-xs text-slate-300 space-y-1">
              <p>Available: <span className="font-mono text-brand-400">{formatCurrency(advance.available)}</span></p>
              <p className="text-slate-500">
                This is money you have already earned this period. It is recovered in full from
                your next pay{parseFloat(advance.fee_percent) > 0 ? `, plus a ${advance.fee_percent}% fee` : ''}.
              </p>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Amount</label>
              <input
                type="text" inputMode="decimal" className="input"
                value={advanceAmount}
                onChange={(e) => setAdvanceAmount(e.target.value)}
                placeholder={advance.min_amount}
                required
              />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowAdvance(false)} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
                {saving && <Loader2 className="w-4 h-4 animate-spin" />} Request
              </button>
            </div>
          </form>
        </div>
      )}

      {viewSlip && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="card w-full max-w-md p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-white">
                  {MONTHS[viewSlip.period_month]} {viewSlip.period_year}
                </h2>
                <p className="text-xs text-slate-400 font-mono">{viewSlip.run_number}</p>
              </div>
              <button onClick={() => setViewSlip(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <table className="w-full text-sm">
              <tbody>
                <tr><td className="py-1 text-slate-300">Basic</td>
                  <td className="py-1 text-right font-mono text-slate-200">{formatCurrency(viewSlip.basic_salary)}</td></tr>
                <tr><td className="py-1 text-slate-300">Housing</td>
                  <td className="py-1 text-right font-mono text-slate-200">{formatCurrency(viewSlip.housing_allowance)}</td></tr>
                <tr><td className="py-1 text-slate-300">Transport</td>
                  <td className="py-1 text-right font-mono text-slate-200">{formatCurrency(viewSlip.transport_allowance)}</td></tr>
                {parseFloat(viewSlip.bonus_amount || '0') > 0 && (
                  <tr><td className="py-1 text-slate-300">Bonus</td>
                    <td className="py-1 text-right font-mono text-slate-200">{formatCurrency(viewSlip.bonus_amount)}</td></tr>
                )}
                <tr className="border-t border-white/10">
                  <td className="py-1.5 text-white font-medium">Gross</td>
                  <td className="py-1.5 text-right font-mono text-white">{formatCurrency(viewSlip.gross_salary)}</td></tr>
                <tr><td className="py-1 text-slate-300">Pension</td>
                  <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(viewSlip.employee_pension)}</td></tr>
                <tr><td className="py-1 text-slate-300">PAYE</td>
                  <td className="py-1 text-right font-mono text-slate-400">−{formatCurrency(viewSlip.paye_tax)}</td></tr>
                <tr className="border-t border-white/10">
                  <td className="py-2 text-white font-semibold">Net</td>
                  <td className="py-2 text-right font-mono text-emerald-400 font-bold">
                    {formatCurrency(viewSlip.net_salary)}
                  </td></tr>
              </tbody>
            </table>
            <button onClick={() => window.print()} className="btn-secondary w-full text-xs">Print</button>
          </div>
        </div>
      )}
    </div>
  )
}
