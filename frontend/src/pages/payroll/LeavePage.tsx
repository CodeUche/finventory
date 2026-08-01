import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CalendarDays, Check, ClipboardList, Loader2, Plus, RefreshCw, X, XCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'

import DateInput from '@/components/DateInput'
import { FieldTooltip } from '@/components/FieldTooltip'
import { confirmDialog } from '@/lib/dialog'
import { payrollApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { Employee, LeaveBalance, LeaveRequest, LeaveType } from '@/types'

type Tab = 'requests' | 'balances' | 'calendar' | 'policies'

const TABS: { key: Tab; label: string }[] = [
  { key: 'requests', label: 'Requests' },
  { key: 'balances', label: 'Balances' },
  { key: 'calendar', label: 'Calendar' },
  { key: 'policies', label: 'Policies' },
]

const STATUS_STYLE: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-400',
  approved: 'bg-emerald-500/15 text-emerald-400',
  rejected: 'bg-red-500/15 text-red-400',
  cancelled: 'bg-slate-500/15 text-slate-400',
  draft: 'bg-slate-500/15 text-slate-400',
}

const today = new Date().toISOString().split('T')[0]

interface RequestForm {
  employee: string
  leave_type: string
  start_date: string
  end_date: string
  reason: string
}

const BLANK_REQUEST: RequestForm = {
  employee: '', leave_type: '', start_date: today, end_date: today, reason: '',
}

interface TypeForm {
  name: string
  days_per_year: string
  accrual_method: 'annual_grant' | 'monthly_accrual'
  is_paid: boolean
  carry_forward_max: string
  gender_restriction: '' | 'male' | 'female'
  requires_approval: boolean
}

const BLANK_TYPE: TypeForm = {
  name: '', days_per_year: '0', accrual_method: 'annual_grant', is_paid: true,
  carry_forward_max: '0', gender_restriction: '', requires_approval: true,
}

/** Working days (Mon–Fri) between two ISO dates, inclusive. */
function workingDays(start: string, end: string): number {
  if (!start || !end) return 0
  const s = new Date(start)
  const e = new Date(end)
  if (e < s) return 0
  let count = 0
  const cur = new Date(s)
  while (cur <= e) {
    if (cur.getDay() !== 0 && cur.getDay() !== 6) count += 1
    cur.setDate(cur.getDate() + 1)
  }
  return count
}

export default function LeavePage() {
  const [tab, setTab] = useState<Tab>('requests')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const [requests, setRequests] = useState<LeaveRequest[]>([])
  const [balances, setBalances] = useState<LeaveBalance[]>([])
  const [types, setTypes] = useState<LeaveType[]>([])
  const [employees, setEmployees] = useState<Employee[]>([])

  const [statusFilter, setStatusFilter] = useState<string>('')
  const [year] = useState(new Date().getFullYear())

  const [showRequest, setShowRequest] = useState(false)
  const [form, setForm] = useState<RequestForm>(BLANK_REQUEST)

  const [showType, setShowType] = useState(false)
  const [typeForm, setTypeForm] = useState<TypeForm>(BLANK_TYPE)
  const [editingType, setEditingType] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [reqRes, balRes, typeRes, empRes] = await Promise.all([
        payrollApi.leaveRequests(statusFilter ? { status: statusFilter } : undefined),
        payrollApi.leaveBalances({ year }),
        payrollApi.leaveTypes(),
        payrollApi.employees({ page_size: 500 }),
      ])
      const unwrap = <T,>(d: unknown): T[] =>
        (Array.isArray(d) ? d : ((d as { results?: T[] })?.results ?? [])) as T[]
      setRequests(unwrap<LeaveRequest>(reqRes.data))
      setBalances(unwrap<LeaveBalance>(balRes.data))
      setTypes(unwrap<LeaveType>(typeRes.data))
      setEmployees(unwrap<Employee>(empRes.data))
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not load leave data')
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, year])

  useEffect(() => { void load() }, [load])

  const pendingCount = useMemo(
    () => requests.filter((r) => r.status === 'pending').length,
    [requests],
  )

  const selectedType = useMemo(
    () => types.find((t) => t.id === form.leave_type),
    [types, form.leave_type],
  )

  const requestedDays = useMemo(
    () => workingDays(form.start_date, form.end_date),
    [form.start_date, form.end_date],
  )

  const employeeById = useMemo(
    () => Object.fromEntries(employees.map((e) => [e.id, e])),
    [employees],
  )

  /** Naira cost of unpaid leave, so an approver sees the consequence up front. */
  const unpaidCost = useCallback((req: LeaveRequest): string | null => {
    if (req.is_paid) return null
    const emp = employeeById[req.employee]
    if (!emp) return null
    const gross = parseFloat(emp.gross_salary || '0')
    const days = parseFloat(req.days || '0')
    if (!gross || !days) return null
    // 22 working days is the conventional month used by the payroll engine's
    // attendance deduction; this is an estimate shown before approval.
    return formatCurrency((gross / 22) * days)
  }, [employeeById])

  async function submitRequest(e: React.FormEvent) {
    e.preventDefault()
    if (!form.employee || !form.leave_type) {
      toast.error('Choose an employee and a leave type')
      return
    }
    setSaving(true)
    try {
      await payrollApi.createLeaveRequest(form)
      toast.success('Leave request recorded')
      setShowRequest(false)
      setForm(BLANK_REQUEST)
      await load()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not record the request')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  async function decide(req: LeaveRequest, action: 'approve' | 'reject') {
    const verb = action === 'approve' ? 'Approve' : 'Reject'
    const cost = unpaidCost(req)
    const detail = action === 'approve' && cost
      ? `This is unpaid leave — approximately ${cost} will be deducted from ${req.employee_name}'s pay.`
      : `${req.days} day(s) of ${req.leave_type_name} for ${req.employee_name}.`
    const ok = await confirmDialog(`${verb} leave request? ${detail}`, { confirmText: verb })
    if (!ok) return
    try {
      if (action === 'approve') await payrollApi.approveLeave(req.id)
      else await payrollApi.rejectLeave(req.id)
      toast.success(`Request ${action === 'approve' ? 'approved' : 'rejected'}`)
      await load()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not update the request')
      toast.error(msg)
    }
  }

  async function cancelRequest(req: LeaveRequest) {
    const ok = await confirmDialog(
      req.status === 'approved'
        ? 'Cancel this leave? The booked days return to the balance and the attendance records are removed.'
        : 'Cancel this leave? The held days return to the balance.',
      { confirmText: 'Cancel leave' },
    )
    if (!ok) return
    try {
      await payrollApi.cancelLeave(req.id)
      toast.success('Leave cancelled')
      await load()
    } catch {
      toast.error('Could not cancel the request')
    }
  }

  async function runAccrual() {
    try {
      const res = await payrollApi.accrueLeave()
      toast.success(`Accrued leave for ${res.data.updated} balance(s)`)
      await load()
    } catch {
      toast.error('Could not run accrual')
    }
  }

  async function saveType(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      if (editingType) await payrollApi.updateLeaveType(editingType, typeForm)
      else await payrollApi.createLeaveType(typeForm)
      toast.success(editingType ? 'Leave type updated' : 'Leave type created')
      setShowType(false)
      setEditingType(null)
      setTypeForm(BLANK_TYPE)
      await load()
    } catch {
      toast.error('Could not save the leave type')
    } finally {
      setSaving(false)
    }
  }

  const balancesByEmployee = useMemo(() => {
    const map: Record<string, LeaveBalance[]> = {}
    for (const b of balances) {
      if (!map[b.employee]) map[b.employee] = []
      map[b.employee].push(b)
    }
    return map
  }, [balances])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <CalendarDays className="w-6 h-6 text-brand-400" />
            Leave
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {pendingCount > 0
              ? `${pendingCount} request${pendingCount === 1 ? '' : 's'} awaiting approval`
              : 'No requests awaiting approval'}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <button onClick={runAccrual} className="btn-secondary flex items-center gap-1.5">
            <RefreshCw className="w-4 h-4" /> Run accrual
          </button>
          <button
            onClick={() => { setEditingType(null); setTypeForm(BLANK_TYPE); setShowType(true) }}
            className="btn-secondary flex items-center gap-1.5"
          >
            <ClipboardList className="w-4 h-4" /> Leave types
          </button>
          <button
            onClick={() => { setForm(BLANK_REQUEST); setShowRequest(true) }}
            className="btn-primary flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> Record leave
          </button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-white/10 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm whitespace-nowrap border-b-2 transition-colors ${
              tab === t.key
                ? 'border-brand-500 text-brand-400 font-semibold'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
            {t.key === 'requests' && pendingCount > 0 && (
              <span className="ml-2 text-[10px] font-mono px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">
                {pendingCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
        </div>
      ) : (
        <>
          {tab === 'requests' && (
            <div className="card overflow-hidden">
              <div className="p-3 border-b border-white/10 flex items-center gap-2">
                <select
                  className="input max-w-[180px]"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="">All statuses</option>
                  <option value="pending">Pending</option>
                  <option value="approved">Approved</option>
                  <option value="rejected">Rejected</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
              {requests.length === 0 ? (
                <div className="p-10 text-center text-slate-400 text-sm">
                  No leave requests yet.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-white/[0.03]">
                      <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                        <th className="px-4 py-3">Employee</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">Dates</th>
                        <th className="px-4 py-3 text-right">Days</th>
                        <th className="px-4 py-3">Payroll effect</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {requests.map((r) => {
                        const cost = unpaidCost(r)
                        return (
                          <tr key={r.id} className="border-t border-white/5">
                            <td className="px-4 py-3 text-white font-medium">{r.employee_name}</td>
                            <td className="px-4 py-3 text-slate-300">{r.leave_type_name}</td>
                            <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                              {formatDate(r.start_date)} – {formatDate(r.end_date)}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-slate-200">{r.days}</td>
                            <td className="px-4 py-3">
                              {r.is_paid ? (
                                <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                                  Paid — no deduction
                                </span>
                              ) : (
                                <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400">
                                  {cost ? `${cost} deduction` : 'Unpaid'}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-xs px-2 py-0.5 rounded capitalize ${STATUS_STYLE[r.status] ?? ''}`}>
                                {r.status}
                              </span>
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-end gap-1">
                                {r.status === 'pending' && (
                                  <>
                                    <button
                                      onClick={() => decide(r, 'approve')}
                                      title="Approve"
                                      className="p-1.5 rounded hover:bg-emerald-500/10 text-emerald-400"
                                    >
                                      <Check className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => decide(r, 'reject')}
                                      title="Reject"
                                      className="p-1.5 rounded hover:bg-red-500/10 text-red-400"
                                    >
                                      <XCircle className="w-4 h-4" />
                                    </button>
                                  </>
                                )}
                                {(r.status === 'pending' || r.status === 'approved') && (
                                  <button
                                    onClick={() => cancelRequest(r)}
                                    title="Cancel"
                                    className="p-1.5 rounded hover:bg-white/5 text-slate-400"
                                  >
                                    <X className="w-4 h-4" />
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {tab === 'balances' && (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {Object.keys(balancesByEmployee).length === 0 ? (
                <div className="card p-10 text-center text-slate-400 text-sm md:col-span-2 xl:col-span-3">
                  No balances yet. Run accrual or record a leave request to create them.
                </div>
              ) : (
                Object.entries(balancesByEmployee).map(([empId, rows]) => (
                  <div key={empId} className="card p-4 space-y-3">
                    <p className="font-semibold text-white text-sm">{rows[0].employee_name}</p>
                    {rows.map((b) => {
                      const available = parseFloat(b.available_days || '0')
                      const entitled = parseFloat(b.entitled_days || '0') || 1
                      const pct = Math.max(0, Math.min(100, (available / entitled) * 100))
                      return (
                        <div key={b.id} className="space-y-1">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-slate-300">{b.leave_type_name}</span>
                            <span className="font-mono text-slate-400">
                              {b.available_days} of {b.entitled_days} d
                            </span>
                          </div>
                          <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <div className="h-full rounded-full bg-brand-500" style={{ width: `${pct}%` }} />
                          </div>
                          <p className="text-[10px] text-slate-500 font-mono">
                            accrued {b.accrued_days} · taken {b.taken_days} · pending {b.pending_days}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                ))
              )}
            </div>
          )}

          {tab === 'calendar' && (
            <div className="card p-4">
              <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">
                Approved leave — next 60 days
              </p>
              {requests.filter((r) => r.status === 'approved').length === 0 ? (
                <p className="text-sm text-slate-400 py-8 text-center">No approved leave scheduled.</p>
              ) : (
                <div className="space-y-2">
                  {requests
                    .filter((r) => r.status === 'approved')
                    .sort((a, b) => a.start_date.localeCompare(b.start_date))
                    .map((r) => (
                      <div
                        key={r.id}
                        className="flex flex-wrap items-center gap-3 p-2.5 rounded-lg bg-white/[0.03] border border-white/5"
                      >
                        <span className="text-sm text-white font-medium min-w-[140px]">{r.employee_name}</span>
                        <span className="text-xs px-2 py-0.5 rounded bg-brand-500/15 text-brand-400">
                          {r.leave_type_name}
                        </span>
                        <span className="text-xs text-slate-400 font-mono">
                          {formatDate(r.start_date)} – {formatDate(r.end_date)}
                        </span>
                        <span className="ml-auto text-xs font-mono text-slate-300">{r.days} d</span>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}

          {tab === 'policies' && (
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-white/[0.03]">
                    <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3 text-right">Days / year</th>
                      <th className="px-4 py-3">Accrual</th>
                      <th className="px-4 py-3">Paid</th>
                      <th className="px-4 py-3 text-right">Carry forward</th>
                      <th className="px-4 py-3">Restriction</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {types.map((t) => (
                      <tr key={t.id} className="border-t border-white/5">
                        <td className="px-4 py-3 text-white font-medium">{t.name}</td>
                        <td className="px-4 py-3 text-right font-mono text-slate-200">{t.days_per_year}</td>
                        <td className="px-4 py-3 text-slate-300">
                          {t.accrual_method === 'monthly_accrual' ? 'Monthly' : 'Granted upfront'}
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            t.is_paid ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                          }`}>
                            {t.is_paid ? 'Paid' : 'Unpaid'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-slate-200">{t.carry_forward_max}</td>
                        <td className="px-4 py-3 text-slate-300 capitalize">
                          {t.gender_restriction || '—'}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => {
                              setEditingType(t.id)
                              setTypeForm({
                                name: t.name,
                                days_per_year: t.days_per_year,
                                accrual_method: t.accrual_method,
                                is_paid: t.is_paid,
                                carry_forward_max: t.carry_forward_max,
                                gender_restriction: t.gender_restriction,
                                requires_approval: t.requires_approval,
                              })
                              setShowType(true)
                            }}
                            className="text-xs text-brand-400 hover:underline"
                          >
                            Edit
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {showRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={submitRequest} className="card w-full max-w-lg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Record leave</h2>
              <button type="button" onClick={() => setShowRequest(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Employee</label>
              <select
                className="input"
                value={form.employee}
                onChange={(e) => setForm({ ...form, employee: e.target.value })}
                required
              >
                <option value="">Select an employee…</option>
                {employees.map((e) => (
                  <option key={e.id} value={e.id}>{e.full_name} — {e.employee_id}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">
                Leave type
                <FieldTooltip text="Unpaid types fall through to the attendance deduction in payroll." />
              </label>
              <select
                className="input"
                value={form.leave_type}
                onChange={(e) => setForm({ ...form, leave_type: e.target.value })}
                required
              >
                <option value="">Select a type…</option>
                {types.filter((t) => t.is_active).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} {t.is_paid ? '' : '(unpaid)'}
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Start date</label>
                <DateInput value={form.start_date} onChange={(v) => setForm({ ...form, start_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">End date</label>
                <DateInput value={form.end_date} onChange={(v) => setForm({ ...form, end_date: v })} />
              </div>
            </div>

            <div className="rounded-lg bg-white/[0.03] border border-white/5 p-3 text-xs text-slate-300">
              <span className="font-mono text-white">{requestedDays}</span> working day(s) — weekends excluded.
              {selectedType && !selectedType.is_paid && (
                <span className="block mt-1 text-red-400">
                  Unpaid leave: this will be deducted from the employee&rsquo;s pay.
                </span>
              )}
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Reason</label>
              <input
                className="input"
                placeholder="Optional"
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              />
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setShowRequest(false)} className="btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                Record leave
              </button>
            </div>
          </form>
        </div>
      )}

      {showType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={saveType} className="card w-full max-w-lg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">
                {editingType ? 'Edit leave type' : 'New leave type'}
              </h2>
              <button type="button" onClick={() => setShowType(false)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Name</label>
              <input
                className="input"
                value={typeForm.name}
                onChange={(e) => setTypeForm({ ...typeForm, name: e.target.value })}
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">
                  Days per year
                  <FieldTooltip text="The Labour Act sets a floor of 6 working days of paid annual leave after 12 months of service." />
                </label>
                <input
                  type="text" inputMode="decimal" className="input"
                  value={typeForm.days_per_year}
                  onChange={(e) => setTypeForm({ ...typeForm, days_per_year: e.target.value })}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Carry-forward cap</label>
                <input
                  type="text" inputMode="decimal" className="input"
                  value={typeForm.carry_forward_max}
                  onChange={(e) => setTypeForm({ ...typeForm, carry_forward_max: e.target.value })}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Accrual</label>
                <select
                  className="input"
                  value={typeForm.accrual_method}
                  onChange={(e) => setTypeForm({
                    ...typeForm,
                    accrual_method: e.target.value as TypeForm['accrual_method'],
                  })}
                >
                  <option value="annual_grant">Granted upfront</option>
                  <option value="monthly_accrual">Accrues monthly</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Restricted to</label>
                <select
                  className="input"
                  value={typeForm.gender_restriction}
                  onChange={(e) => setTypeForm({
                    ...typeForm,
                    gender_restriction: e.target.value as TypeForm['gender_restriction'],
                  })}
                >
                  <option value="">No restriction</option>
                  <option value="female">Female only</option>
                  <option value="male">Male only</option>
                </select>
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={typeForm.is_paid}
                onChange={(e) => setTypeForm({ ...typeForm, is_paid: e.target.checked })}
              />
              Paid leave (unpaid types are deducted in payroll)
            </label>

            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={typeForm.requires_approval}
                onChange={(e) => setTypeForm({ ...typeForm, requires_approval: e.target.checked })}
              />
              Requires approval
            </label>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => setShowType(false)} className="btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                Save
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
