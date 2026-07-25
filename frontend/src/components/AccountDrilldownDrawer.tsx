import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { X, Loader2, ExternalLink } from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { sourceDocLabel, sourceDocRoute } from '@/lib/sourceDoc'

interface GLLine {
  date: string
  reference: string
  description: string
  debit: number
  credit: number
  balance: number
  journal_entry_id: string
  source_type: string
  source_ref: string
}
interface GLSection {
  account_code: string
  account_name: string
  opening_balance: number
  lines: GLLine[]
  closing_balance: number
}

/**
 * Drill-down drawer: given an account code, shows its GL activity (running balance)
 * for the period and lets the user jump to the source document behind each line.
 * Drives the "click any statement number → see what's behind it" flow.
 */
export default function AccountDrilldownDrawer({
  accountCode, accountName, dateFrom, dateTo, onClose,
}: {
  accountCode: string
  accountName?: string
  dateFrom?: string
  dateTo?: string
  onClose: () => void
}) {
  const [section, setSection] = useState<GLSection | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    ;(async () => {
      setLoading(true)
      try {
        const params: Record<string, string> = { account_code: accountCode, period: 'custom' }
        if (dateFrom) params.date_from = dateFrom
        if (dateTo) params.date_to = dateTo
        const { data } = await reportApi.run('gl-detail', params)
        if (active) setSection(data?.data?.accounts?.[0] ?? null)
      } catch {
        if (active) toast.error('Failed to load account activity')
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [accountCode, dateFrom, dateTo])

  const goToSource = (line: GLLine) => {
    const route = sourceDocRoute(line.source_type)
    if (route) navigate(route)
    else toast(`${sourceDocLabel(line.source_type)} · ${line.reference}`, { icon: 'ℹ️' })
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="w-full max-w-2xl h-full bg-surface-900 border-l border-surface-700 overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-surface-900 border-b border-surface-700 px-5 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-white">
              {accountCode} — {section?.account_name ?? accountName ?? 'Account activity'}
            </h2>
            <p className="text-xs text-slate-400">General ledger detail</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={18} /></button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24 text-slate-400"><Loader2 className="animate-spin" /></div>
        ) : !section || section.lines.length === 0 ? (
          <div className="px-5 py-16 text-center text-slate-400 text-sm">No activity for this account in the period.</div>
        ) : (
          <div className="px-5 py-4">
            <div className="flex justify-between text-xs text-slate-400 mb-2">
              <span>Opening balance</span><span>{formatCurrency(section.opening_balance)}</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-slate-400 text-left border-b border-surface-700">
                  <th className="py-1.5 pr-2">Date</th>
                  <th className="py-1.5 px-2">Source</th>
                  <th className="py-1.5 px-2 text-right">Debit</th>
                  <th className="py-1.5 px-2 text-right">Credit</th>
                  <th className="py-1.5 pl-2 text-right">Balance</th>
                </tr>
              </thead>
              <tbody>
                {section.lines.map((ln, i) => (
                  <tr key={i} className="border-b border-surface-700/50 hover:bg-surface-800/50">
                    <td className="py-1.5 pr-2 text-slate-300 whitespace-nowrap">{formatDate(ln.date)}</td>
                    <td className="py-1.5 px-2">
                      <button onClick={() => goToSource(ln)}
                        className="text-brand-400 hover:underline inline-flex items-center gap-1">
                        {sourceDocLabel(ln.source_type)}
                        {sourceDocRoute(ln.source_type) && <ExternalLink size={11} />}
                      </button>
                      <div className="text-[11px] text-slate-500">{ln.reference || ln.description}</div>
                    </td>
                    <td className="py-1.5 px-2 text-right text-slate-300">{ln.debit ? formatCurrency(ln.debit) : ''}</td>
                    <td className="py-1.5 px-2 text-right text-slate-300">{ln.credit ? formatCurrency(ln.credit) : ''}</td>
                    <td className="py-1.5 pl-2 text-right text-white font-medium">{formatCurrency(ln.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-between text-sm font-semibold text-white mt-3 pt-2 border-t border-surface-700">
              <span>Closing balance</span><span>{formatCurrency(section.closing_balance)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
