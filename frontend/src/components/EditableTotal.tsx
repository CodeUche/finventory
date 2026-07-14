/**
 * EditableTotal — the invoice/sale Total row with an inline "edit total" mode.
 *
 * When the user types a new total and applies it, the exact allocator
 * (lib/totalAllocator) redistributes the amount into per-line UNIT PRICES,
 * proportional to each line's current contribution, preserving quantities and
 * discounts. The result is forward-verified; if the precise figure is
 * unreachable at 4-dp price precision the user is told the nearest exact
 * total instead of being silently mispriced.
 */
import { useState } from 'react'
import { Pencil, Check, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { allocateTotal, type AllocLine } from '@/lib/totalAllocator'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'

interface Props {
  /** Current grand total (display) */
  total: number
  /** Current lines (quantities, prices, discounts) */
  lines: AllocLine[]
  /** Called with the new 4-dp unit prices (one per line) after allocation */
  onApply: (prices: number[]) => void
  /** Extra class for the total value text */
  valueClass?: string
}

export default function EditableTotal({ total, lines, onApply, valueClass = 'text-brand-400' }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const start = () => {
    if (!lines.length || lines.every((l) => l.quantity <= 0)) {
      toast.error('Add line items before adjusting the total.')
      return
    }
    setDraft(formatAmountInput(String(total.toFixed(2))))
    setEditing(true)
  }

  const apply = () => {
    const target = parseFloat(stripCommas(draft))
    if (!isFinite(target) || target < 0) { toast.error('Enter a valid total amount.'); return }
    const result = allocateTotal(lines, target)
    if (!result) { toast.error('Could not adjust the total — check the line items.'); return }
    onApply(result.prices)
    setEditing(false)
    if (result.exact) {
      toast.success(`Unit prices recalculated — lines now total exactly ${formatCurrency(result.achievedTotal)}.`)
    } else {
      // Unreachable at 4-dp price precision — be explicit, never silently off.
      toast(`${formatCurrency(target)} isn't reachable with these quantities — set to the nearest exact total: ${formatCurrency(result.achievedTotal)}.`, { icon: 'ℹ️', duration: 7000 })
    }
  }

  if (!editing) {
    return (
      <div className="flex justify-between items-center font-bold">
        <span className="text-white flex items-center gap-2">
          Total
          <button
            type="button"
            onClick={start}
            title="Edit total — unit prices will be recalculated to match"
            className="p-1 rounded-md text-slate-500 hover:text-brand-400 hover:bg-brand-500/10 transition-colors"
          >
            <Pencil size={13} />
          </button>
        </span>
        <span className={valueClass}>{formatCurrency(total)}</span>
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between items-center gap-3 font-bold">
        <span className="text-white shrink-0">Total</span>
        <div className="flex items-center gap-1.5 flex-1 justify-end">
          <input
            className="input py-1.5 text-right font-bold max-w-[180px]"
            autoFocus
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(formatAmountInput(e.target.value))}
            onKeyDown={(e) => { if (e.key === 'Enter') apply(); if (e.key === 'Escape') setEditing(false) }}
          />
          <button type="button" onClick={apply} title="Apply — recalculate unit prices"
            className="p-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
            <Check size={15} />
          </button>
          <button type="button" onClick={() => setEditing(false)} title="Cancel"
            className="p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-surface-700 transition-colors">
            <X size={15} />
          </button>
        </div>
      </div>
      <p className="text-[11px] font-normal text-slate-500 text-right">
        Unit prices will be adjusted proportionally (quantities &amp; discounts stay unchanged).
      </p>
    </div>
  )
}
