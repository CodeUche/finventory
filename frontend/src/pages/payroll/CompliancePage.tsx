import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, Download, FileText, Loader2, ShieldCheck, X,
} from 'lucide-react'
import toast from 'react-hot-toast'

import { payrollApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type {
  RemittanceScheduleGroup, RemittanceSummary, StatutoryRemittance,
} from '@/types'

const TYPE_STYLE: Record<string, string> = {
  paye: 'bg-brand-500/15 text-brand-400',
  pension: 'bg-sky-500/15 text-sky-400',
  nhf: 'bg-violet-500/15 text-violet-400',
  nsitf: 'bg-amber-500/15 text-amber-400',
  itf: 'bg-slate-500/15 text-slate-300',
  benefit: 'bg-cyan-500/15 text-cyan-400',
}

/** GL account each obligation clears against — mirrors AccountingService.CODES. */
const GL_CODE: Record<string, string> = {
  paye: '2200', pension: '2300', nhf: '2600',
  nsitf: '2500', itf: '2750', benefit: '2900',
}

const SCHEDULE_TYPES = [
  { key: 'pension', label: 'Pension (per PFA)' },
  { key: 'paye', label: 'PAYE (per State IRS)' },
  { key: 'nhf', label: 'NHF' },
  { key: 'nsitf', label: 'NSITF' },
]

export default function CompliancePage() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<StatutoryRemittance[]>([])
  const [summary, setSummary] = useState<RemittanceSummary | null>(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const [remitting, setRemitting] = useState<StatutoryRemittance | null>(null)
  const [reference, setReference] = useState('')
  const [amountPaid, setAmountPaid] = useState('')
  const [saving, setSaving] = useState(false)

  const [scheduleType, setScheduleType] = useState<string | null>(null)
  const [schedule, setSchedule] = useState<RemittanceScheduleGroup[]>([])
  const [scheduleLoading, setScheduleLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (typeFilter) params.remittance_type = typeFilter
      if (statusFilter) params.status = statusFilter
      const [listRes, sumRes] = await Promise.all([
        payrollApi.remittances(params),
        payrollApi.remittanceSummary(),
      ])
      const data = listRes.data
      setRows(Array.isArray(data) ? data : (data?.results ?? []))
      setSummary(sumRes.data)
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not load obligations')
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }, [typeFilter, statusFilter])

  useEffect(() => { void load() }, [load])

  const glTotal = useMemo(
    () => rows
      .filter((r) => r.status !== 'remitted')
      .reduce((sum, r) => sum + parseFloat(r.balance_due || '0'), 0),
    [rows],
  )

  async function openSchedule(type: string) {
    setScheduleType(type)
    setScheduleLoading(true)
    try {
      const res = await payrollApi.remittanceSchedule({ type })
      setSchedule(res.data.groups ?? [])
    } catch {
      toast.error('Could not build the schedule')
      setSchedule([])
    } finally {
      setScheduleLoading(false)
    }
  }

  function downloadScheduleCsv() {
    if (!schedule.length || !scheduleType) return
    const lines: string[] = []
    lines.push(`Schedule,${scheduleType.toUpperCase()}`)
    lines.push('')
    for (const group of schedule) {
      lines.push(`Recipient,${group.recipient}`)
      lines.push(`Employees,${group.count},Total,${group.total}`)
      const keys = Object.keys(group.employees[0] ?? {})
      lines.push(keys.join(','))
      for (const emp of group.employees) {
        lines.push(keys.map((k) => String(emp[k] ?? '')).join(','))
      }
      lines.push('')
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${scheduleType}-schedule.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function submitRemittance(e: React.FormEvent) {
    e.preventDefault()
    if (!remitting) return
    setSaving(true)
    try {
      await payrollApi.markRemitted(remitting.id, {
        reference,
        ...(amountPaid ? { amount_paid: amountPaid } : {}),
      })
      toast.success('Remittance recorded and the GL liability cleared')
      setRemitting(null)
      setReference('')
      setAmountPaid('')
      await load()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : ((apiErr as { message?: string })?.message ?? 'Could not record the remittance')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-6 h-6 text-brand-400" />
            Statutory &amp; benefit obligations
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {summary?.next_due_date
              ? `Next deadline ${formatDate(summary.next_due_date)} — ${summary.next_due_recipient ?? ''}`
              : 'Everything remitted'}
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          {SCHEDULE_TYPES.map((s) => (
            <button key={s.key} onClick={() => openSchedule(s.key)} className="btn-secondary text-xs">
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="card p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Outstanding</p>
          <p className="text-xl font-bold text-amber-400 mt-1 font-mono">
            {formatCurrency(summary?.outstanding ?? 0)}
          </p>
          <p className="text-[11px] text-slate-500 font-mono mt-0.5">
            across {summary?.outstanding_count ?? 0} obligations
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Overdue</p>
          <p className={`text-xl font-bold mt-1 font-mono ${
            (summary?.overdue_count ?? 0) > 0 ? 'text-red-400' : 'text-slate-300'
          }`}>
            {formatCurrency(summary?.overdue ?? 0)}
          </p>
          <p className="text-[11px] text-slate-500 font-mono mt-0.5">
            {summary?.overdue_count ?? 0} obligations
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Remitted YTD</p>
          <p className="text-xl font-bold text-emerald-400 mt-1 font-mono">
            {formatCurrency(summary?.remitted_ytd ?? 0)}
          </p>
        </div>
        <div className="card p-4">
          <p className="text-[10px] uppercase tracking-wider text-slate-400">GL liability</p>
          <p className="text-xl font-bold text-white mt-1 font-mono">{formatCurrency(glTotal)}</p>
          <p className="text-[11px] text-emerald-400 font-mono mt-0.5 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> matches outstanding
          </p>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="p-3 border-b border-white/10 flex flex-wrap items-center gap-2">
          <select className="input max-w-[190px]" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All obligations</option>
            <option value="paye">PAYE</option>
            <option value="pension">Pension</option>
            <option value="nhf">NHF</option>
            <option value="nsitf">NSITF</option>
            <option value="itf">ITF</option>
            <option value="benefit">Benefits</option>
          </select>
          <select className="input max-w-[160px]" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="partial">Partial</option>
            <option value="remitted">Remitted</option>
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-slate-400 text-sm">
            No obligations yet — run payroll to generate them.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-white/[0.03]">
                <tr className="text-left text-xs uppercase tracking-wider text-slate-400">
                  <th className="px-4 py-3">Obligation</th>
                  <th className="px-4 py-3">Authority / provider</th>
                  <th className="px-4 py-3">Basis</th>
                  <th className="px-4 py-3">Period</th>
                  <th className="px-4 py-3 text-right">Due</th>
                  <th className="px-4 py-3">Deadline</th>
                  <th className="px-4 py-3">GL</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className={`border-t border-white/5 ${r.is_overdue ? 'bg-red-500/[0.04]' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded font-semibold uppercase ${TYPE_STYLE[r.remittance_type] ?? ''}`}>
                        {r.remittance_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-white font-medium">{r.authority_name || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{r.basis}</td>
                    <td className="px-4 py-3 text-slate-300 font-mono text-xs whitespace-nowrap">
                      {r.period_month === 0
                        ? `${r.period_year} (annual)`
                        : `${r.period_year}-${String(r.period_month).padStart(2, '0')}`}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-slate-100">
                      {formatCurrency(r.balance_due)}
                    </td>
                    <td className="px-4 py-3 text-slate-300 text-xs whitespace-nowrap">
                      {formatDate(r.due_date)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">
                      {GL_CODE[r.remittance_type] ?? '—'}
                      {r.gl_cleared && <CheckCircle2 className="w-3 h-3 inline ml-1 text-emerald-400" />}
                    </td>
                    <td className="px-4 py-3">
                      {r.status === 'remitted' ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                          Remitted
                        </span>
                      ) : r.is_overdue ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400 flex items-center gap-1 w-fit">
                          <AlertTriangle className="w-3 h-3" /> {r.days_overdue}d overdue
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 capitalize">
                          {r.status}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {r.status !== 'remitted' && (
                        <button
                          onClick={() => {
                            setRemitting(r)
                            setAmountPaid(r.balance_due)
                            setReference(r.reference || '')
                          }}
                          className="text-xs text-brand-400 hover:underline whitespace-nowrap"
                        >
                          Mark remitted
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {remitting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={submitRemittance} className="card w-full max-w-md p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-white">Record remittance</h2>
              <button type="button" onClick={() => setRemitting(null)} className="text-slate-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="rounded-lg bg-white/[0.03] border border-white/5 p-3 space-y-1 text-sm">
              <p className="text-white font-medium">{remitting.authority_name}</p>
              <p className="text-xs text-slate-400">{remitting.basis}</p>
              <p className="font-mono text-brand-400">{formatCurrency(remitting.balance_due)} outstanding</p>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Amount paid</label>
              <input
                type="text" inputMode="decimal" className="input"
                value={amountPaid}
                onChange={(e) => setAmountPaid(e.target.value)}
              />
              <p className="text-[11px] text-slate-500 mt-1">
                Leave as-is to settle in full. A smaller amount records a partial remittance.
              </p>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Payment reference</label>
              <input
                className="input"
                placeholder="e.g. LIRS/PAYE/2026/06/001"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
            </div>

            <p className="text-[11px] text-slate-500">
              Settling in full posts the clearing journal, so the liability leaves the balance sheet.
            </p>

            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setRemitting(null)} className="btn-secondary">Cancel</button>
              <button type="submit" disabled={saving} className="btn-primary flex items-center gap-1.5">
                {saving && <Loader2 className="w-4 h-4 animate-spin" />}
                Record remittance
              </button>
            </div>
          </form>
        </div>
      )}

      {scheduleType && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="card w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-white/10 flex items-center gap-3">
              <FileText className="w-5 h-5 text-brand-400" />
              <div>
                <h2 className="font-semibold text-white capitalize">{scheduleType} filing schedule</h2>
                <p className="text-xs text-slate-400">
                  One group per recipient — a PFA or State IRS will not accept a blended file.
                </p>
              </div>
              <div className="ml-auto flex items-center gap-2">
                <button onClick={downloadScheduleCsv} className="btn-secondary flex items-center gap-1.5 text-xs">
                  <Download className="w-4 h-4" /> CSV
                </button>
                <button onClick={() => setScheduleType(null)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="overflow-y-auto p-4 space-y-4">
              {scheduleLoading ? (
                <div className="flex items-center justify-center py-10">
                  <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
                </div>
              ) : schedule.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-8">
                  Nothing to file for this obligation yet.
                </p>
              ) : (
                schedule.map((group) => (
                  <div key={group.recipient} className="rounded-lg border border-white/10 overflow-hidden">
                    <div className="px-3 py-2 bg-white/[0.03] flex items-center gap-3">
                      <span className="text-sm font-semibold text-white">{group.recipient}</span>
                      <span className="text-xs text-slate-400">{group.count} employee(s)</span>
                      <span className="ml-auto font-mono text-brand-400 text-sm">
                        {formatCurrency(group.total)}
                      </span>
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-slate-400 border-b border-white/10">
                          <th className="px-3 py-1.5">ID</th>
                          <th className="px-3 py-1.5">Name</th>
                          <th className="px-3 py-1.5 text-right">Gross</th>
                          <th className="px-3 py-1.5 text-right">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {group.employees.map((emp) => (
                          <tr key={String(emp.employee_id)} className="border-b border-white/5">
                            <td className="px-3 py-1.5 font-mono text-slate-400">{emp.employee_id}</td>
                            <td className="px-3 py-1.5 text-slate-200">{emp.name}</td>
                            <td className="px-3 py-1.5 text-right font-mono text-slate-400">
                              {formatCurrency(emp.gross)}
                            </td>
                            <td className="px-3 py-1.5 text-right font-mono text-slate-100">
                              {formatCurrency(emp.amount)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
