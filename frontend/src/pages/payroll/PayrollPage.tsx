import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Banknote, Loader2, ExternalLink } from 'lucide-react'
import toast from 'react-hot-toast'
import { payrollApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { PayrollRun } from '@/types'

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
      load()
    } catch { toast.error('Failed to mark payroll as paid') }
  }

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
      <div className="card p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4">
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
      </div>

      {/* Summary from latest run */}
      {latestRun && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="card p-5"><p className="text-xs text-slate-400">Total Gross</p><p className="text-xl font-bold text-white mt-1">{formatCurrency(latestRun.total_gross)}</p></div>
          <div className="card p-5"><p className="text-xs text-slate-400">Total PAYE Tax</p><p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(latestRun.total_paye)}</p></div>
          <div className="card p-5"><p className="text-xs text-slate-400">Pension (Employee)</p><p className="text-xl font-bold text-orange-400 mt-1">{formatCurrency(latestRun.total_pension_employee)}</p></div>
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
              { label: 'FIRS PAYE Tax', amount: latestRun.total_paye, color: 'text-red-400', note: 'Remit to FIRS by 10th of following month', link: 'https://www.firs.gov.ng' },
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
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <Banknote size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No payroll runs yet. Click "Run Payroll" to get started.</p>
                  </td>
                </tr>
              ) : runs.map((r) => (
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
                                {['Employee', 'Gross', 'PAYE', 'Pension (Emp)', 'NHF', 'Deductions', 'Net Pay'].map((h) => (
                                  <th key={h} className="pb-2 text-left text-slate-500 uppercase tracking-wider">{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-700">
                              {r.payslips.map((p) => (
                                <tr key={p.id}>
                                  <td className="py-2 text-slate-300">{p.employee_name}</td>
                                  <td className="py-2 font-mono text-white">{formatCurrency(p.gross_salary)}</td>
                                  <td className="py-2 font-mono text-red-400">{formatCurrency(p.paye_tax)}</td>
                                  <td className="py-2 font-mono text-orange-400">{formatCurrency(p.employee_pension)}</td>
                                  <td className="py-2 font-mono text-blue-400">{formatCurrency(p.nhf)}</td>
                                  <td className="py-2 font-mono text-slate-400">{formatCurrency(p.total_deductions)}</td>
                                  <td className="py-2 font-mono text-emerald-400">{formatCurrency(p.net_salary)}</td>
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

      {/* Mark Paid Modal */}
      {markPayId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setMarkPayId(null)} />
          <div className="relative card w-full max-w-sm p-6 space-y-5">
            <h2 className="text-lg font-bold text-white">Mark Payroll as Paid</h2>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Payment Date</label>
              <input type="date" className="input" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} />
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setMarkPayId(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center" onClick={handleMarkPaid}>Confirm</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
