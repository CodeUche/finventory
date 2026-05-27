/**
 * Reusable sortable table for report pages.
 *
 * Usage:
 *   <ReportTable
 *     headers={['Name', 'Amount', 'Date']}
 *     rows={data.map(r => [r.name, formatCurrency(r.amount), r.date])}
 *     loading={loading}
 *     emptyMessage="No data for the selected period."
 *   />
 */

import { useState } from 'react'
import { ChevronUp, ChevronDown, ChevronsUpDown, Loader2 } from 'lucide-react'

type CellValue = string | number | null | undefined

interface Props {
  headers: string[]
  rows: CellValue[][]
  loading?: boolean
  emptyMessage?: string
  /** Columns that should right-align (0-indexed) */
  rightAlignCols?: number[]
  className?: string
}

type SortDir = 'asc' | 'desc' | null

function parseForSort(v: CellValue): number | string {
  if (v == null || v === '') return ''
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/[^0-9.-]/g, ''))
  return isNaN(n) ? String(v).toLowerCase() : n
}

export default function ReportTable({
  headers,
  rows,
  loading = false,
  emptyMessage = 'No data for the selected period.',
  rightAlignCols = [],
  className = '',
}: Props) {
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const handleSort = (idx: number) => {
    if (sortCol !== idx) {
      setSortCol(idx)
      setSortDir('asc')
    } else if (sortDir === 'asc') {
      setSortDir('desc')
    } else if (sortDir === 'desc') {
      setSortCol(null)
      setSortDir(null)
    }
  }

  const sorted = sortCol !== null && sortDir !== null
    ? [...rows].sort((a, b) => {
        const va = parseForSort(a[sortCol])
        const vb = parseForSort(b[sortCol])
        if (va < vb) return sortDir === 'asc' ? -1 : 1
        if (va > vb) return sortDir === 'asc' ? 1 : -1
        return 0
      })
    : rows

  const SortIcon = ({ idx }: { idx: number }) => {
    if (sortCol !== idx) return <ChevronsUpDown size={12} className="text-slate-600" />
    if (sortDir === 'asc')  return <ChevronUp   size={12} className="text-brand-400" />
    return <ChevronDown size={12} className="text-brand-400" />
  }

  return (
    <div className={`overflow-x-auto rounded-xl border border-surface-700 ${className}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-surface-800 border-b border-surface-700">
            {headers.map((h, i) => (
              <th
                key={i}
                onClick={() => handleSort(i)}
                className={`px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide cursor-pointer select-none hover:text-slate-200 transition-colors
                  ${rightAlignCols.includes(i) ? 'text-right' : 'text-left'}`}
              >
                <span className="inline-flex items-center gap-1">
                  {h}
                  <SortIcon idx={i} />
                </span>
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {loading ? (
            <tr>
              <td colSpan={headers.length} className="px-4 py-12 text-center">
                <Loader2 size={22} className="animate-spin mx-auto text-slate-500" />
              </td>
            </tr>
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={headers.length} className="px-4 py-10 text-center text-slate-500 text-sm">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            sorted.map((row, ri) => (
              <tr
                key={ri}
                className={`border-b border-surface-700 last:border-0 transition-colors
                  ${ri % 2 === 0 ? 'bg-transparent' : 'bg-surface-900/40'}
                  hover:bg-surface-700/60`}
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className={`px-4 py-3 text-slate-200
                      ${rightAlignCols.includes(ci) ? 'text-right tabular-nums' : ''}`}
                  >
                    {cell == null || cell === '' ? <span className="text-slate-600">—</span> : cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
