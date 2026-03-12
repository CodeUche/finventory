import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Banknote, Loader2, ExternalLink, Send, CheckCircle, XCircle, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { payrollApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { PayrollRun } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter from '@/components/YearFilter'

interface TransferResult {
  employee: string
  name: string
  status: 'queued' | 'initiated' | 'skipped' | 'failed'
  account?: string
  bank?: string
  amount?: number
  reason?: string
  transfer_code?: string
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate', processing: 'badge-yellow', approved: 'badge-blue', paid: 'badge-green',
}

export default function PayrollPage() {
  const [runs, setRuns] = useState<PayrollRun[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedRun, setExpandedRun] = useState<string | null>(null)

  const now = new Date()
  const [selectedYear, setSelectedYear] = useState(now.getFullYear())
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1)
  const [running, setRunning] = useState(false)

  const [markPayId, setMarkPayId] = useState<string | null>(null)
  const [paymentDate, setPaymentDate] = useState(now.toISOString().split('T')[0])
  const [initiatingTransfer, setInitiatingTransfer] = useState(false)
  const [transferResults, setTransferResults] = useState<TransferResult[] | null>(null)
  const [archiveYear, setArchiveYear] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await payrollApi.runs()
      setRuns(data.results ?? data)
    } catch { toast.error('Failed to load payroll runs') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleRunPayroll = async () => {
    if (!confirm(`Run payroll for ${MONTHS[selectedMonth - 1]} ${selectedYear}? This will compute salaries and statutory deductions for all active employees.`)) return
    setRunning(true)
    try {
      await payrollApi.runPayroll({ period_year: selectedYear, period_month: selectedMonth })
      toast.success('Payroll run created successfully')
      load()
    } catch { toast.error('Failed to run payroll — check if a run already exists for this period') }
    finally { setRunning(false) }
  }

  const handleApprove = async (id: string) => {
    if (!confirm('Approve this payroll run?')) return
    try { await payrollApi.approvePayroll(id); toast.success('Payroll approved'); load() }
    catch { toast.error('Failed to approve payroll') }
  }

  const handleMarkPaid = async () => {
    if (!markPayId) return
    try {
      await payrollApi.markPaid(markPayId, { payment_date: paymentDate })
      toast.success('Payroll marked as paid')
      setMarkPayId(null)
      setTransferResults(null)
      load()
    } catch { toast.error('Failed to mark payroll as paid') }
  }

  const handleInitiateTransfers = async () => {
    if (!markPayId) return
    setInitiatingTransfer(true)
    setTransferResults(null)
    try {
      const { data } = await payrollApi.initiateTransfers(markPayId)
      setTransferResults(data.results ?? [])
      if (data.success) {
        toast.success(data.message ?? 'Transfers initiated')
        // Auto-mark as paid after successful transfer initiation
        await payrollApi.markPaid(markPayId, { payment_date: paymentDate })
        load()
      } else {
        toast.error(data.error ?? data.message ?? 'Transfer failed')
      }
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? err?.response?.data?.message ?? 'Transfer initiation failed'
      toast.error(msg)
    } finally {
      setInitiatingTransfer(false)
    }
  }

  const displayRuns = archiveYear ? runs.filter((r) => r.period_year === archiveYear) : runs
  // Latest run for summary cards
  const latestRun = runs.find((r) => r.status === 'approved' || r.status === 'paid') ?? runs[0]

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Payroll Runs</h1>
        <p className="text-slate-400 text-sm">Manage monthly payroll and statutory remittances</p>
      </div>

      {/* Run Payroll bar */}
      <div className="card p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4 flex-wrap">
        <p className="text-white font-semibold">Run Payroll for:</p>
        <div className="flex items-center gap-2">
          <select className="input py-1.5" value={selectedMonth} onChange={(e) => setSelectedMonth(parseInt(e.target.value))}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select className="input py-1.5" value={selectedYear} onChange={(e) => setSelectedYear(parseInt(e.target.value))}>
            {[now.getFullYear() - 1, now.getFullYear(), now.getFullYear() + 1].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <button onClick={handleRunPayroll} disabled={running} className="btn-primary flex items-center gap-2">
            {running ? <Loader2 size={15} className="animate-spin" /> : <Banknote size={15} />}
            Run Payroll
          </button>
        </div>
        <div className="sm:ml-auto">
          <YearFilter selectedYear={archiveYear} onChange={setArchiveYear} />
        </div>
      </div>

      {/* Summary from latest run */}
      {latestRun && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
          <div className="card p-5"><p className="text-xs text-slate-400">Total Gross</p><p className="text-xl font-bold text-white mt-1">{formatCurrency(latestRun.total_gross)}</p></div>
          <div className="card p-5"><p className="text-xs text-slate-400">Total PAYE Tax</p><p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(latestRun.total_paye)}</p></div>
          <div className="card p-5"><p className="text-xs text-slate-400">Pension (Employee)</p><p className="text-xl font-bold text-orange-400 mt-1">{formatCurrency(latestRun.total_pension_employee)}</p></div>
          <div className="card p-5">
            <p className="text-xs text-slate-400">Penalties &amp; Loans</p>
            <p className="text-xl font-bold text-rose-400 mt-1">
              {formatCurrency(
                latestRun.payslips.reduce((s, p) => s + parseFloat(p.penalty_deductions || '0') + parseFloat(p.loan_deductions || '0'), 0)
              )}
            </p>
          </div>
          <div className="card p-5"><p className="text-xs text-slate-400">Total Net Pay</p><p className="text-xl font-bold text-emerald-400 mt-1">{formatCurrency(latestRun.total_net)}</p></div>
        </div>
      )}

      {/* Statutory Remittances */}
      {latestRun && (
        <div className="card p-6 space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-white font-semibold">Statutory Remittances</h3>
            <span className="text-xs text-slate-500">({MONTHS[latestRun.period_month - 1]} {latestRun.period_year})</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[
              { label: 'FIRS PAYE Tax', amount: latestRun.total_paye, color: 'text-red-400', note: 'Remit to FIRS by 10th of following month', link: 'https://taxpromax.firs.gov.ng/' },
              { label: 'Pension (Employee 8%)', amount: latestRun.total_pension_employee, color: 'text-orange-400', note: 'Remit to PFA within 7 days of payment' },
              { label: 'Pension (Employer 10%)', amount: latestRun.total_pension_employer, color: 'text-yellow-400', note: 'Employer contribution to PFA' },
              { label: 'NHF (2.5%)', amount: latestRun.total_nhf, color: 'text-blue-400', note: 'Remit to Federal Mortgage Bank' },
              { label: 'NSITF (1%)', amount: latestRun.total_nsitf, color: 'text-purple-400', note: 'Social insurance — remit to NSITF' },
            ].map((item) => (
              <div key={item.label} className="p-4 bg-surface-900/50 rounded-xl border border-surface-700">
                <div className="flex items-start justify-between">
                  <p className="text-xs text-slate-400">{item.label}</p>
                  {item.link && (
                    <a href={item.link} target="_blank" rel="noopener noreferrer" className="text-brand-400 hover:text-brand-300">
                      <ExternalLink size={12} />
                    </a>
                  )}
                </div>
                <p className={`text-lg font-bold ${item.color} mt-1`}>{formatCurrency(item.amount)}</p>
                <p className="text-xs text-slate-600 mt-1">{item.note}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Runs table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['', 'Run #', 'Period', 'Status', 'Total Gross', 'Total PAYE', 'Total Net', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : displayRuns.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <Banknote size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">{archiveYear ? `No payroll runs for ${archiveYear}.` : 'No payroll runs yet. Click "Run Payroll" to get started.'}</p>
                  </td>
                </tr>
              ) : displayRuns.map((r) => (
                <>
                  <tr key={r.id} className="table-row">
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRun(expandedRun === r.id ? null : r.id)} className="text-slate-400 hover:text-white">
                        {expandedRun === r.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-brand-400">{r.run_number}</td>
                    <td className="px-4 py-3.5 text-slate-300">{MONTHS[r.period_month - 1]} {r.period_year}</td>
                    <td className="px-4 py-3.5"><span className={STATUS_BADGE[r.status] ?? 'badge-slate'}>{r.status}</span></td>
                    <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(r.total_gross)}</td>
                    <td className="px-4 py-3.5 font-mono text-red-400">{formatCurrency(r.total_paye)}</td>
                    <td className="px-4 py-3.5 font-mono text-emerald-400">{formatCurrency(r.total_net)}</td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {r.status === 'processing' && (
                          <button onClick={() => handleApprove(r.id)} className="text-xs px-2.5 py-1 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 transition-colors">Approve</button>
                        )}
                        {r.status === 'approved' && (
                          <button onClick={() => { setMarkPayId(r.id); setPaymentDate(now.toISOString().split('T')[0]) }} className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors">Mark Paid</button>
                        )}
                        {r.payment_date && <span className="text-xs text-slate-500">{formatDate(r.payment_date)}</span>}
                      </div>
                    </td>
                  </tr>
                  {expandedRun === r.id && (
                    <tr key={`${r.id}-payslips`} className="bg-surface-900/50">
                      <td colSpan={8} className="px-6 py-4">
                        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Employee Payslips</p>
                        <div className="overflow-x-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-surface-700">
                                {['Employee', 'Gross', 'PAYE', 'Pension (Emp)', 'NHF', 'Penalties', 'Loans', 'Total Deductions', 'Net Pay'].map((h) => (
                                  <th key={h} className="pb-2 pr-4 text-left text-slate-500 uppercase tracking-wider">{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-700">
                              {r.payslips.map((p) => (
                                <tr key={p.id}>
                                  <td className="py-2 pr-4 text-slate-300">{p.employee_name}</td>
                                  <td className="py-2 pr-4 font-mono text-white">{formatCurrency(p.gross_salary)}</td>
                                  <td className="py-2 pr-4 font-mono text-red-400">{formatCurrency(p.paye_tax)}</td>
                                  <td className="py-2 pr-4 font-mono text-orange-400">{formatCurrency(p.employee_pension)}</td>
                                  <td className="py-2 pr-4 font-mono text-blue-400">{formatCurrency(p.nhf)}</td>
                                  <td className="py-2 pr-4 font-mono text-rose-400">
                                    {parseFloat(p.penalty_deductions) > 0 ? formatCurrency(p.penalty_deductions) : <span className="text-slate-600">—</span>}
                                  </td>
                                  <td className="py-2 pr-4 font-mono text-amber-400">
                                    {parseFloat(p.loan_deductions) > 0 ? formatCurrency(p.loan_deductions) : <span className="text-slate-600">—</span>}
                                  </td>
                                  <td className="py-2 pr-4 font-mono text-slate-400">{formatCurrency(p.total_deductions)}</td>
                                  <td className="py-2 font-mono text-emerald-400 font-semibold">{formatCurrency(p.net_salary)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Mark Paid / Transfer Modal */}
      {markPayId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setMarkPayId(null); setTransferResults(null) }} />
          <div className="relative bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl max-h-[90vh] flex flex-col">
            <div className="p-6 border-b border-surface-700">
              <h2 className="text-lg font-bold text-white">Pay Employees</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {runs.find(r => r.id === markPayId)?.run_number} —{' '}
                {formatCurrency(runs.find(r => r.id === markPayId)?.total_net ?? 0)} net
              </p>
            </div>

            <div className="p-6 space-y-5 overflow-y-auto flex-1">
              {/* Payment date */}
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Date</label>
                <DateInput value={paymentDate} onChange={setPaymentDate} />
              </div>

              {/* Payslip preview — employees and bank details */}
              {(() => {
                const run = runs.find(r => r.id === markPayId)
                if (!run) return null
                return (
                  <div>
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
                      {run.payslips.length} Employee{run.payslips.length !== 1 ? 's' : ''}
                    </p>
                    <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                      {run.payslips.map((p) => {
                        const hasBankDetails = (p as any).employee_account_number && (p as any).employee_bank_code
                        const result = transferResults?.find(r => r.employee === (p as any).employee_id_str)
                        return (
                          <div key={p.id} className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs ${hasBankDetails ? 'border-surface-600 bg-surface-700/30' : 'border-amber-500/20 bg-amber-500/5'}`}>
                            <div className="min-w-0 flex-1">
                              <p className="text-white font-medium truncate">{p.employee_name}</p>
                              {hasBankDetails ? (
                                <p className="text-slate-500">{(p as any).employee_bank_name} · {(p as any).employee_account_number}</p>
                              ) : (
                                <p className="text-amber-500 flex items-center gap-1"><AlertTriangle size={10} /> No bank details</p>
                              )}
                            </div>
                            <div className="text-right ml-3 shrink-0">
                              <p className="font-mono text-emerald-400 font-semibold">{formatCurrency(p.net_salary)}</p>
                              {result && (
                                <p className={`text-[10px] mt-0.5 flex items-center gap-1 justify-end ${result.status === 'initiated' ? 'text-emerald-400' : result.status === 'skipped' || result.status === 'failed' ? 'text-red-400' : 'text-slate-400'}`}>
                                  {result.status === 'initiated' ? <CheckCircle size={10} /> : result.status === 'skipped' || result.status === 'failed' ? <XCircle size={10} /> : null}
                                  {result.status}
                                </p>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })()}

              {/* Transfer results summary */}
              {transferResults && (
                <div className={`rounded-xl p-4 text-sm border ${transferResults.some(r => r.status === 'initiated') ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                  <p className="font-semibold text-white mb-1">Transfer Results</p>
                  <p className="text-slate-300 text-xs">
                    Initiated: {transferResults.filter(r => r.status === 'initiated').length} ·{' '}
                    Skipped: {transferResults.filter(r => r.status === 'skipped').length} ·{' '}
                    Failed: {transferResults.filter(r => r.status === 'failed').length}
                  </p>
                  {transferResults.filter(r => r.status === 'skipped' || r.status === 'failed').map((r, i) => (
                    <p key={i} className="text-amber-400 text-xs mt-1">{r.name}: {r.reason}</p>
                  ))}
                </div>
              )}
            </div>

            <div className="p-6 border-t border-surface-700 space-y-2">
              {/* Paystack transfer button */}
              {!transferResults?.some(r => r.status === 'initiated') && (
                <button
                  onClick={handleInitiateTransfers}
                  disabled={initiatingTransfer}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl bg-brand-500 hover:bg-brand-600 text-white font-semibold text-sm transition-colors disabled:opacity-50"
                >
                  {initiatingTransfer ? <Loader2 size={16} className="animate-spin" /> : <Send size={15} />}
                  {initiatingTransfer ? 'Initiating transfers…' : 'Pay via Paystack (Bulk Transfer)'}
                </button>
              )}
              <div className="flex gap-2">
                <button
                  className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                  onClick={() => { setMarkPayId(null); setTransferResults(null) }}
                >
                  Cancel
                </button>
                <button
                  className="flex-1 py-2.5 rounded-xl border border-slate-600 text-slate-300 hover:bg-surface-700 transition-colors text-sm"
                  onClick={handleMarkPaid}
                >
                  Mark as Paid (Manual)
                </button>
              </div>
              <p className="text-center text-[10px] text-slate-600">
                Paystack transfers require sufficient balance and a verified business account.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
