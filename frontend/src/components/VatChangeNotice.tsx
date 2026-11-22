import { useEffect, useState } from 'react'
import { taxApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'

interface ComparisonRow {
  period_start: string
  period_end: string
  reports_page_showed: string
  tax_page_showed: string
  now: string
  difference_from_reports_page: string
  difference_from_tax_page: string
  different: boolean
  why: string[]
}

/**
 * Shown on the Tax page VAT tab and the Reports Overview VAT card. Closed periods
 * only (the last 12 months): what the old Reports and Tax screens showed against the
 * single VAT calculation every screen now uses. The words are "different from",
 * never "you owe" or "you overpaid". Hidden quietly when the person has no Tax
 * access (the comparison sits behind the Tax permission) or nothing differs.
 */
export default function VatChangeNotice() {
  const [rows, setRows] = useState<ComparisonRow[] | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    taxApi.vatComparison()
      .then(({ data }) => { if (!cancelled) setRows(data.rows ?? []) })
      .catch(() => { if (!cancelled) setRows(null) })
    return () => { cancelled = true }
  }, [])

  const changed = (rows ?? []).filter((r) => r.different)
  if (changed.length === 0) return null

  return (
    <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm" role="region" aria-label="VAT figures have changed">
      <p className="font-semibold text-amber-200">VAT figures have changed</p>
      <p className="text-slate-300 mt-1">
        Audity now uses one VAT calculation everywhere. This is how it differs from what you may have seen:
      </p>
      <ul className="list-disc pl-5 mt-2 text-slate-300 space-y-0.5">
        <li>invoices past due are now included;</li>
        <li>credit notes are deducted in the month they are issued;</li>
        <li>input VAT is counted only if your business is VAT registered and the supplier is VAT registered, or the bill carries the supplier tax ID and invoice reference (otherwise it is not counted until checked);</li>
        <li>exempt purchases are not claimed;</li>
        <li>a negative result is shown as a possible refund instead of zero.</li>
      </ul>
      <button type="button" onClick={() => setOpen((o) => !o)} className="mt-3 text-amber-300 hover:text-amber-200 text-xs font-semibold">
        {open ? 'Hide' : 'Show'} the comparison for {changed.length} earlier {changed.length === 1 ? 'month' : 'months'}
      </button>
      {open && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-400 border-b border-surface-700">
                <th className="py-2 pr-3">Period</th>
                <th className="py-2 pr-3">Reports page showed</th>
                <th className="py-2 pr-3">Tax page showed</th>
                <th className="py-2 pr-3">Now</th>
                <th className="py-2 pr-3">Different from Reports page</th>
                <th className="py-2 pr-3">Different from Tax page</th>
                <th className="py-2">Why</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {changed.map((r) => (
                <tr key={r.period_start} className="align-top">
                  <td className="py-2 pr-3 text-white whitespace-nowrap">{formatDate(r.period_start)} – {formatDate(r.period_end)}</td>
                  <td className="py-2 pr-3 font-mono">{formatCurrency(r.reports_page_showed)}</td>
                  <td className="py-2 pr-3 font-mono">{formatCurrency(r.tax_page_showed)}</td>
                  <td className="py-2 pr-3 font-mono text-white">{formatCurrency(r.now)}</td>
                  <td className="py-2 pr-3 font-mono">{formatCurrency(r.difference_from_reports_page)}</td>
                  <td className="py-2 pr-3 font-mono">{formatCurrency(r.difference_from_tax_page)}</td>
                  <td className="py-2 text-slate-300">
                    <ul className="list-disc pl-4 space-y-0.5">{r.why.map((w) => <li key={w}>{w}</li>)}</ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-slate-400 mt-3">
            If you filed a return for an earlier period using an older Audity screen, compare it with the figure above.
            If the new figure is different, do not change anything yourself. Show the comparison to your tax practitioner,
            who can tell you whether an amended return is needed.
          </p>
        </div>
      )}
    </div>
  )
}
