import { useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import DateInput from '@/components/DateInput'
import AmountInput from '@/components/AmountInput'
import { formatCurrency, stripCommas } from '@/lib/utils'

type Side = 'debit' | 'credit'
type Mode = 'increase' | 'decrease' | 'set'

interface Props {
  partyName: string
  partyLabel: 'Customer' | 'Supplier'
  /** Signed current balance in the party's natural direction (e.g. Customer:
   *  positive = owes us; Supplier: positive = we owe them). */
  currentBalance: number
  /** Which side counts as "positive" for this party type — Customer is debit,
   *  Supplier is credit. Drives the DR/CR label shown on save. */
  naturalSide: Side
  onClose: () => void
  onSave: (amount: number, side: Side, asOfDate: string) => Promise<void>
}

const today = new Date().toISOString().split('T')[0]

export default function AdjustOpeningBalanceModal({ partyName, partyLabel, currentBalance, naturalSide, onClose, onSave }: Props) {
  const [mode, setMode] = useState<Mode>('increase')
  const [amountStr, setAmountStr] = useState('')
  const [asOfDate, setAsOfDate] = useState(today)
  const [saving, setSaving] = useState(false)

  const amount = parseFloat(stripCommas(amountStr)) || 0
  const targetSigned =
    mode === 'increase' ? currentBalance + amount :
    mode === 'decrease' ? currentBalance - amount :
    amount
  const resultSide: Side = targetSigned >= 0 ? naturalSide : (naturalSide === 'debit' ? 'credit' : 'debit')
  const resultAmount = Math.abs(targetSigned)

  const handleSave = async () => {
    if (amount <= 0 && mode !== 'set') { return }
    setSaving(true)
    try {
      await onSave(resultAmount, resultSide, asOfDate)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-md shadow-2xl animate-slide-up">
        <div className="flex items-center justify-between p-6 border-b border-surface-700">
          <h2 className="font-semibold text-white text-lg">Adjust Opening Balance</h2>
          <button onClick={onClose} className="btn-ghost p-1.5"><X size={18} /></button>
        </div>
        <div className="p-6 space-y-4">
          <div>
            <label className="text-xs text-slate-400 block">{partyLabel}</label>
            <p className="text-white font-medium">{partyName}</p>
          </div>
          <div>
            <label className="text-xs text-slate-400 block">Current opening balance</label>
            <p className={`text-lg font-bold ${currentBalance >= 0 ? 'text-emerald-400' : 'text-amber-400'}`}>
              {formatCurrency(String(currentBalance))}
            </p>
          </div>
          <div>
            <label className="label">Adjustment</label>
            <div className="grid grid-cols-3 gap-2">
              <button type="button" onClick={() => setMode('increase')}
                className={`py-2 rounded-lg text-sm font-medium transition-colors ${mode === 'increase' ? 'bg-brand-500 text-white' : 'bg-surface-700 text-slate-300 hover:bg-surface-600'}`}>
                + Increase
              </button>
              <button type="button" onClick={() => setMode('decrease')}
                className={`py-2 rounded-lg text-sm font-medium transition-colors ${mode === 'decrease' ? 'bg-brand-500 text-white' : 'bg-surface-700 text-slate-300 hover:bg-surface-600'}`}>
                − Decrease
              </button>
              <button type="button" onClick={() => setMode('set')}
                className={`py-2 rounded-lg text-sm font-medium transition-colors ${mode === 'set' ? 'bg-brand-500 text-white' : 'bg-surface-700 text-slate-300 hover:bg-surface-600'}`}>
                Set to
              </button>
            </div>
          </div>
          <div>
            <label className="label">Amount</label>
            <AmountInput className="input" placeholder="0.00" value={amountStr} onChange={setAmountStr} />
            <p className="text-[11px] text-slate-500 mt-1">Enter the amount as a positive number.</p>
          </div>
          <div>
            <label className="label">Opening Balance As At</label>
            <DateInput value={asOfDate} onChange={setAsOfDate} />
          </div>
          {(amount > 0 || mode === 'set') && (
            <p className="text-xs text-slate-400 bg-surface-900/50 rounded-lg px-3 py-2">
              This will record a <span className={resultSide === 'debit' ? 'text-red-400 font-semibold' : 'text-emerald-400 font-semibold'}>{resultSide === 'debit' ? 'Debit' : 'Credit'}</span> of{' '}
              <span className="text-white font-semibold">{formatCurrency(String(resultAmount))}</span> as of {asOfDate}.
            </p>
          )}
          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-secondary flex-1 justify-center">Cancel</button>
            <button type="button" onClick={handleSave} disabled={saving} className="btn-primary flex-1 justify-center">
              {saving ? <Loader2 size={16} className="animate-spin" /> : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
