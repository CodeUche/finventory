import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight } from 'lucide-react'

const PAGE_SIZES = [25, 50, 75, 100]

interface Props {
  page: number
  totalPages: number
  pageSize: number
  total: number
  onPage: (p: number) => void
  onPageSize: (s: number) => void
}

export default function Pagination({ page, totalPages, pageSize, total, onPage, onPageSize }: Props) {
  if (total === 0) return null

  const start = (page - 1) * pageSize + 1
  const end   = Math.min(page * pageSize, total)

  // Build visible page numbers with ellipsis markers
  const visible = new Set<number>()
  visible.add(1)
  visible.add(totalPages)
  for (let i = Math.max(1, page - 1); i <= Math.min(totalPages, page + 1); i++) visible.add(i)

  const sorted = Array.from(visible).sort((a, b) => a - b)
  const buttons: (number | '…')[] = []
  let prev: number | null = null
  for (const p of sorted) {
    if (prev !== null && p - prev > 1) buttons.push('…')
    buttons.push(p)
    prev = p
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-surface-700">
      {/* Left: rows-per-page + count */}
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span>Rows per page:</span>
        <select
          className="input py-1 px-2 text-xs w-16"
          value={pageSize}
          onChange={(e) => { onPageSize(Number(e.target.value)); onPage(1) }}
        >
          {PAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <span className="ml-1 tabular-nums">
          {start}–{end} <span className="text-slate-500">of</span> {total.toLocaleString()}
        </span>
      </div>

      {/* Right: page buttons */}
      <div className="flex items-center gap-0.5">
        <button
          onClick={() => onPage(1)} disabled={page === 1}
          className="btn-ghost p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title="First page"
        >
          <ChevronFirst size={15} />
        </button>
        <button
          onClick={() => onPage(page - 1)} disabled={page === 1}
          className="btn-ghost p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title="Previous page"
        >
          <ChevronLeft size={15} />
        </button>

        {buttons.map((b, i) =>
          b === '…'
            ? <span key={`e${i}`} className="px-1.5 text-slate-500 text-xs select-none">…</span>
            : <button
                key={b}
                onClick={() => onPage(b)}
                className={`min-w-[28px] h-7 px-1 rounded-lg text-xs font-medium transition-colors ${
                  b === page
                    ? 'bg-brand-500 text-white'
                    : 'btn-ghost text-slate-400 hover:text-white'
                }`}
              >
                {b}
              </button>
        )}

        <button
          onClick={() => onPage(page + 1)} disabled={page === totalPages}
          className="btn-ghost p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title="Next page"
        >
          <ChevronRight size={15} />
        </button>
        <button
          onClick={() => onPage(totalPages)} disabled={page === totalPages}
          className="btn-ghost p-1.5 text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
          title="Last page"
        >
          <ChevronLast size={15} />
        </button>
      </div>
    </div>
  )
}
