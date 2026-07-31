/**
 * Reusable sortable table for report pages.
 *
 * Usage:
 *   <ReportTable
 *     headers={['Name', 'Amount', 'Date']}
 *     rows={data.map(r => [r.name, formatCurrency(r.amount), r.date])}
 *     loading={loading}
 *     emptyMessage="No data for the selected period."
 *     paginate                       // opt-in paging for long lists
 *     onRowClick={(i) => open(data[i])}  // i indexes the ORIGINAL rows array
 *   />
 */

import { useEffect, useMemo, useState } from 'react'
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
  /** Show pagination controls when the row count exceeds pageSize. */
  paginate?: boolean
  pageSize?: number
  /**
   * Row click handler. Receives the index into the ORIGINAL `rows` array —
   * safe across sorting and paging (a DOM index is neither).
   */
  onRowClick?: (originalIndex: number) => void
}

type SortDir = 'asc' | 'desc' | null

function parseForSort(v: CellValue): number | string {
  if (v == null || v === '') return ''
  const n = typeof v === 'number' ? v : parseFloat(String(v).replace(/[^0-9.-]/g, ''))
  return isNaN(n) ? String(v).toLowerCase() : n
}

const PAGE_SIZES = [25, 50, 100]

export default function ReportTable({
  headers,
  rows,
  loading = false,
  emptyMessage = 'No data for the selected period.',
  rightAlignCols = [],
  className = '',
  paginate = false,
  pageSize: initialPageSize = 25,
  onRowClick,
}: Props) {
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(initialPageSize)

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

  // Carry each row's original index through sorting so onRowClick stays correct.
  const sorted = useMemo(() => {
    const indexed = rows.map((row, idx) => ({ row, idx }))
    if (sortCol === null || sortDir === null) return indexed
    return [...indexed].sort((a, b) => {
      const va = parseForSort(a.row[sortCol])
      const vb = parseForSort(b.row[sortCol])
      if (va < vb) return sortDir === 'asc' ? -1 : 1
      if (va > vb) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [rows, sortCol, sortDir])

  const totalPages = paginate ? Math.max(1, Math.ceil(sorted.length / pageSize)) : 1

  // Keep the page in range when data shrinks (filter/period change).
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  // A new sort should return the reader to the first page.
  useEffect(() => { setPage(1) }, [sortCol, sortDir, pageSize])

  const visible = paginate
    ? sorted.slice((page - 1) * pageSize, page * pageSize)
    : sorted

  const SortIcon = ({ idx }: { idx: number }) => {
    if (sortCol !== idx) return <ChevronsUpDown size={12} className="text-slate-600" />
    if (sortDir === 'asc')  return <ChevronUp   size={12} className="text-brand-400" />
    return <ChevronDown size={12} className="text-brand-400" />
  }

  const firstShown = sorted.length === 0 ? 0 : (page - 1) * pageSize + 1
  const lastShown = Math.min(page * pageSize, sorted.length)

  return (
    <div className={className}>
      <div className="overflow-x-auto rounded-xl border border-surface-700">
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
            ) : visible.length === 0 ? (
              <tr>
                <td colSpan={headers.length} className="px-4 py-10 text-center text-slate-500 text-sm">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              visible.map(({ row, idx }, ri) => (
                <tr
                  key={idx}
                  onClick={onRowClick ? () => onRowClick(idx) : undefined}
                  className={`border-b border-surface-700 last:border-0 transition-colors
                    ${ri % 2 === 0 ? 'bg-transparent' : 'bg-surface-900/40'}
                    hover:bg-surface-700/60 ${onRowClick ? 'cursor-pointer' : ''}`}
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

      {paginate && !loading && sorted.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 px-1 pt-2.5 text-xs text-slate-400">
          <span>
            Showing <span className="text-slate-200">{firstShown}–{lastShown}</span> of{' '}
            <span className="text-slate-200">{sorted.length}</span>
          </span>

          <label className="flex items-center gap-1.5 ml-auto">
            <span>Rows</span>
            <select
              value={pageSize}
              onChange={(e) => setPageSize(Number(e.target.value))}
              className="input py-1 px-2 text-xs w-auto"
              aria-label="Rows per page"
            >
              {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2.5 py-1 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 disabled:hover:text-slate-400"
            >
              Prev
            </button>
            <span className="tabular-nums">Page {page} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2.5 py-1 rounded-lg bg-surface-800 border border-surface-700 hover:text-white disabled:opacity-40 disabled:hover:text-slate-400"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
