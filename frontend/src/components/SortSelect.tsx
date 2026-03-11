import { ArrowUpDown } from 'lucide-react'

interface Option { label: string; value: string }

interface Props {
  value: string
  onChange: (v: string) => void
  options: Option[]
}

export default function SortSelect({ value, onChange, options }: Props) {
  return (
    <div className="flex items-center gap-1.5 bg-surface-800 border border-surface-700 rounded-xl px-3 py-2 text-sm cursor-pointer focus-within:border-brand-500 transition-colors">
      <ArrowUpDown size={13} className="text-slate-500 shrink-0" />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-transparent text-slate-300 text-sm border-none outline-none cursor-pointer"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-surface-800 text-white">
            {o.label}
          </option>
        ))}
      </select>
    </div>
  )
}
