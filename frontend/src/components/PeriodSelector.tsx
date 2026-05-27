/**
 * Period selector: Today | This Week | This Month | This Year | All Time | Custom.
 * When Custom is selected, two date inputs appear for date_from and date_to.
 */

import { useState } from 'react'
import { Calendar, ChevronDown } from 'lucide-react'
import DateInput from '@/components/DateInput'

export type PeriodKey = 'today' | 'week' | 'month' | 'year' | 'all' | 'custom'

export interface PeriodValue {
  period: PeriodKey
  date_from?: string   // ISO YYYY-MM-DD
  date_to?: string     // ISO YYYY-MM-DD
}

interface Props {
  value: PeriodValue
  onChange: (v: PeriodValue) => void
  className?: string
}

const OPTIONS: { label: string; value: PeriodKey }[] = [
  { label: 'Today',      value: 'today' },
  { label: 'This Week',  value: 'week'  },
  { label: 'This Month', value: 'month' },
  { label: 'This Year',  value: 'year'  },
  { label: 'All Time',   value: 'all'   },
  { label: 'Custom',     value: 'custom'},
]

export function periodLabel(v: PeriodValue): string {
  const opt = OPTIONS.find(o => o.value === v.period)
  if (!opt) return 'Period'
  if (v.period !== 'custom') return opt.label
  if (v.date_from && v.date_to) return `${v.date_from} – ${v.date_to}`
  if (v.date_from) return `From ${v.date_from}`
  if (v.date_to)   return `To ${v.date_to}`
  return 'Custom Range'
}

export default function PeriodSelector({ value, onChange, className = '' }: Props) {
  const [open, setOpen] = useState(false)

  const select = (period: PeriodKey) => {
    setOpen(false)
    if (period === 'custom') {
      onChange({ period, date_from: value.date_from, date_to: value.date_to })
    } else {
      onChange({ period })
    }
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      {/* Dropdown */}
      <div className="relative">
        <button
          onClick={() => setOpen(v => !v)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-surface-800 border border-surface-700 text-sm text-slate-200 hover:border-slate-500 transition-colors"
        >
          <Calendar size={14} className="text-slate-400" />
          <span>{OPTIONS.find(o => o.value === value.period)?.label ?? 'Period'}</span>
          <ChevronDown size={12} className="text-slate-400" />
        </button>

        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div className="absolute left-0 top-full mt-1 z-50 bg-surface-800 border border-surface-700 rounded-xl shadow-xl overflow-hidden w-40">
              {OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => select(opt.value)}
                  className={`w-full px-4 py-2.5 text-sm text-left transition-colors
                    ${value.period === opt.value
                      ? 'text-brand-400 bg-surface-700'
                      : 'text-slate-300 hover:bg-surface-700'
                    }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Custom date range inputs */}
      {value.period === 'custom' && (
        <>
          <DateInput
            value={value.date_from ?? ''}
            onChange={v => onChange({ ...value, date_from: v || undefined })}
            placeholder="From date"
            className="w-36 text-sm"
          />
          <span className="text-slate-500 text-sm">–</span>
          <DateInput
            value={value.date_to ?? ''}
            onChange={v => onChange({ ...value, date_to: v || undefined })}
            placeholder="To date"
            className="w-36 text-sm"
          />
        </>
      )}
    </div>
  )
}
