/**
 * MonthFilter — a compact monthly archive selector for module pages.
 *
 * Shows "This Month" (no filter) plus the last N months as archive options.
 * Mutually exclusive with YearFilter — selecting a month should clear any
 * active year filter (handled at the page level via the onChange callback).
 *
 * When a past month is selected it returns { date_from, date_to } params
 * spanning the first to last day of that month for API calls.
 */

import { CalendarDays, ChevronDown } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

export interface ArchiveMonth {
  year: number
  month: number   // 1–12
}

export interface MonthFilterProps {
  selectedMonth: ArchiveMonth | null   // null = current month (no filter)
  onChange: (month: ArchiveMonth | null) => void
  monthsBack?: number                   // how many past months to show (default 18)
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Returns { date_from, date_to } for API params, or {} for current month */
export function monthToDateParams(m: ArchiveMonth | null): Record<string, string> {
  if (!m) return {}
  // Use local date parts (not toISOString) to avoid UTC timezone off-by-one
  const fmt = (y: number, mo: number, d: number) =>
    `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  const lastDay = new Date(m.year, m.month, 0).getDate()  // day 0 of next month = last day
  return { date_from: fmt(m.year, m.month, 1), date_to: fmt(m.year, m.month, lastDay) }
}

/** Human-readable label for an ArchiveMonth, e.g. "Mar 2025" */
export function formatArchiveMonth(m: ArchiveMonth): string {
  return `${MONTH_NAMES[m.month - 1]} ${m.year}`
}

export default function MonthFilter({ selectedMonth, onChange, monthsBack = 18 }: MonthFilterProps) {
  const now = new Date()
  const currentYear  = now.getFullYear()
  const currentMonth = now.getMonth() + 1  // 1–12

  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Build list of past months (most-recent first), excluding the current month
  const pastMonths: ArchiveMonth[] = []
  for (let i = 1; i <= monthsBack; i++) {
    let m = currentMonth - i
    let y = currentYear
    while (m <= 0) { m += 12; y -= 1 }
    pastMonths.push({ year: y, month: m })
  }

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const isArchive = !!selectedMonth
  const label = selectedMonth ? `${formatArchiveMonth(selectedMonth)} Archive` : 'This Month'

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-sm transition-colors ${
          isArchive
            ? 'bg-amber-500/10 border-amber-500/30 text-amber-300 hover:bg-amber-500/20'
            : 'border-surface-600 text-slate-400 hover:text-white hover:border-surface-500'
        }`}
      >
        <CalendarDays size={14} className="shrink-0" />
        <span>{label}</span>
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl overflow-hidden z-30 min-w-[172px] max-h-64 overflow-y-auto">
          <button
            type="button"
            onClick={() => { onChange(null); setOpen(false) }}
            className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${!selectedMonth ? 'bg-brand-500/20 text-brand-300' : 'text-slate-200 hover:bg-surface-700'}`}
          >
            This Month ({MONTH_NAMES[currentMonth - 1]} {currentYear})
          </button>
          {pastMonths.map((m) => {
            const isSelected = selectedMonth?.year === m.year && selectedMonth?.month === m.month
            return (
              <button
                key={`${m.year}-${m.month}`}
                type="button"
                onClick={() => { onChange(m); setOpen(false) }}
                className={`w-full text-left px-3 py-2.5 text-sm transition-colors flex items-center gap-2 ${isSelected ? 'bg-amber-500/20 text-amber-300' : 'text-slate-200 hover:bg-surface-700'}`}
              >
                <CalendarDays size={13} className="opacity-60 shrink-0" />
                {formatArchiveMonth(m)} Archive
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
