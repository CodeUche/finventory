/**
 * GeneralLedgerPage — consolidated General Ledger report.
 * Every account with activity in the selected range, its opening balance, each
 * posted line with a running balance, and its closing balance. One of the three
 * reports requested in the COA/GL feedback (General Ledger, Journal, Balance).
 */
import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { BookOpen, Loader2, RefreshCw, Download, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { saveBlobFile } from '@/lib/saveBlobFile'
import DateInput from '@/components/DateInput'

interface GLLine { date: string; reference: string; description: string; debit: string; credit: string; balance: string }
interface GLAccount { code: string; name: string; account_type: string; opening_balance: string; closing_balance: string; lines: GLLine[] }

const toISO = (dd: string) => {
  if (!dd) return ''
  const [d, m, y] = dd.split('/'); return d && m && y ? `${y}-${m}-${d}` : dd
}

export default function GeneralLedgerPage() {
  const [data, setData] = useState<GLAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      const f = toISO(from), t = toISO(to)
      if (f) params.date_from = f
      if (t) params.date_to = t
      const { data: d } = await accountingApi.generalLedger(params)
      setData(d.accounts ?? [])
    } catch { toast.error('Failed to load general ledger') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const exportCSV = async () => {
    const rows: string[] = ['Account Code,Account Name,Date,Reference,Description,Debit,Credit,Balance']
    for (const a of data) {
      rows.push(`${a.code},"${a.name}",,,Opening Balance,,,${a.opening_balance}`)
      for (const l of a.lines) {
        rows.push(`${a.code},"${a.name}",${l.date},${l.reference},"${(l.description || '').replace(/"/g, '""')}",${l.debit},${l.credit},${l.balance}`)
      }
      rows.push(`${a.code},"${a.name}",,,Closing Balance,,,${a.closing_balance}`)
    }
    await saveBlobFile(new Blob([rows.join('\n')], { type: 'text/csv' }), `general-ledger-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">General Ledger</h1>
          <p className="text-slate-400 text-sm">{data.length} accounts with activity</p>
        </div>
        <div className="sm:ml-auto flex items-end gap-2 flex-wrap">
          <div>
            <label className="text-[11px] text-slate-500 block mb-1">From</label>
            <DateInput value={from} onChange={setFrom} />
          </div>
          <div>
            <label className="text-[11px] text-slate-500 block mb-1">To</label>
            <DateInput value={to} onChange={setTo} />
          </div>
          <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Apply
          </button>
          {data.length > 0 && (
            <button onClick={exportCSV} className="btn-ghost flex items-center gap-2 text-sm"><Download size={14} /> Export CSV</button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="card p-12 text-center text-slate-500"><Loader2 size={20} className="animate-spin inline" /></div>
      ) : data.length === 0 ? (
        <div className="card p-12 text-center">
          <BookOpen size={32} className="mx-auto mb-2 text-slate-600" />
          <p className="text-slate-500">No posted ledger activity in this range</p>
        </div>
      ) : data.map((a) => {
        const open = expanded[a.code] ?? true
        return (
          <div key={a.code} className="card p-0 overflow-hidden">
            <button onClick={() => setExpanded((e) => ({ ...e, [a.code]: !open }))}
              className="w-full flex items-center justify-between px-5 py-3 hover:bg-surface-700/40 transition-colors">
              <div className="flex items-center gap-3">
                {open ? <ChevronUp size={15} className="text-slate-400" /> : <ChevronDown size={15} className="text-slate-400" />}
                <span className="font-mono text-slate-400 text-sm">{a.code}</span>
                <span className="text-white font-medium">{a.name}</span>
              </div>
              <div className="text-right">
                <span className="text-xs text-slate-500 mr-2">Closing</span>
                <span className="font-mono text-white">{formatCurrency(a.closing_balance)}</span>
              </div>
            </button>
            {open && (
              <div className="overflow-x-auto border-t border-surface-700">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700 bg-surface-800/40">
                      {['Date', 'Reference', 'Description', 'Debit', 'Credit', 'Balance'].map((h, i) => (
                        <th key={h} className={`px-4 py-2 text-xs font-semibold text-slate-400 uppercase ${i >= 3 ? 'text-right' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-800">
                    <tr className="text-slate-400 italic">
                      <td className="px-4 py-2" colSpan={3}>Opening Balance</td>
                      <td /><td />
                      <td className="px-4 py-2 text-right font-mono">{formatCurrency(a.opening_balance)}</td>
                    </tr>
                    {a.lines.map((l, i) => (
                      <tr key={i} className="table-row">
                        <td className="px-4 py-2 text-slate-400">{formatDate(l.date)}</td>
                        <td className="px-4 py-2 font-mono text-brand-400">{l.reference}</td>
                        <td className="px-4 py-2 text-slate-300">{l.description}</td>
                        <td className="px-4 py-2 text-right font-mono text-white">{parseFloat(l.debit) > 0 ? formatCurrency(l.debit) : '—'}</td>
                        <td className="px-4 py-2 text-right font-mono text-white">{parseFloat(l.credit) > 0 ? formatCurrency(l.credit) : '—'}</td>
                        <td className="px-4 py-2 text-right font-mono text-white">{formatCurrency(l.balance)}</td>
                      </tr>
                    ))}
                    <tr className="font-semibold border-t border-surface-600">
                      <td className="px-4 py-2 text-slate-300" colSpan={5}>Closing Balance</td>
                      <td className="px-4 py-2 text-right font-mono text-white">{formatCurrency(a.closing_balance)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
