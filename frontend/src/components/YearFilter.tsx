/**
 * YearFilter — a compact archive year selector for module pages.
 *
 * Shows "Current" (no year restriction) plus the last N years as archive options.
 * When a past year is selected it returns dateRange params for API calls.
 */

import { Archive, ChevronDown } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

export interface YearFilterProps {
  selectedYear: number | null          // null = current year (no filter)
  onChange: (year: number | null) => void
  yearsBack?: number                    // how many past years to show (default 5)
}

/** Returns { date_from, date_to } for API params, or {} for current year */
export function yearToDateParams(year: number | null): Record<string, string> {
  if (!year) return {}
  return {
    date_from: `${year}-01-01`,
    date_to:   `${year}-12-31`,
  }
}

export default function YearFilter({ selectedYear, onChange, yearsBack = 5 }: YearFilterProps) {
  const currentYear = new Date().getFullYear()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const years = Array.from({ length: yearsBack }, (_, i) => currentYear - 1 - i)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const label = selectedYear ? `${selectedYear} Archive` : 'Current'
  const isArchive = !!selectedYear

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
        {isArchive && <Archive size={14} className="shrink-0" />}
        <span>{label}</span>
        <ChevronDown size={14} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-2xl overflow-hidden z-30 min-w-[160px]">
          <button
            type="button"
            onClick={() => { onChange(null); setOpen(false) }}
            className={`w-full text-left px-3 py-2.5 text-sm transition-colors ${!selectedYear ? 'bg-brand-500/20 text-brand-300' : 'text-slate-200 hover:bg-surface-700'}`}
          >
            Current ({currentYear})
          </button>
          {years.map((y) => (
            <button
              key={y}
              type="button"
              onClick={() => { onChange(y); setOpen(false) }}
              className={`w-full text-left px-3 py-2.5 text-sm transition-colors flex items-center gap-2 ${selectedYear === y ? 'bg-amber-500/20 text-amber-300' : 'text-slate-200 hover:bg-surface-700'}`}
            >
              <Archive size={13} className="opacity-60" />
              {y} Archive
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
