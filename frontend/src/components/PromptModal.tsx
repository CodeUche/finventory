/**
 * PromptModal — themed replacement for the native window.prompt(), which the
 * Tauri desktop WebView renders as an ugly unstyled "tauri.localhost says" box.
 * Controlled: parent holds `open` and the target being acted on.
 */
import { useEffect, useState } from 'react'
import { X, Loader2 } from 'lucide-react'

interface Props {
  open: boolean
  title: string
  description?: string
  label?: string
  placeholder?: string
  confirmText?: string
  confirmClass?: string
  /** When true the field may be left empty (default true). */
  optional?: boolean
  multiline?: boolean
  busy?: boolean
  onConfirm: (value: string) => void
  onCancel: () => void
}

export default function PromptModal({
  open, title, description, label, placeholder, confirmText = 'Confirm',
  confirmClass = 'btn-primary', optional = true, multiline = true, busy = false,
  onConfirm, onCancel,
}: Props) {
  const [value, setValue] = useState('')

  // Reset the field each time the modal opens.
  useEffect(() => { if (open) setValue('') }, [open])

  if (!open) return null

  const canConfirm = optional || value.trim().length > 0
  const submit = () => { if (canConfirm && !busy) onConfirm(value.trim()) }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => !busy && onCancel()} />
      <div className="relative card w-full max-w-md p-6 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-white">{title}</h2>
            {description && <p className="text-xs text-slate-400 mt-0.5">{description}</p>}
          </div>
          <button onClick={() => !busy && onCancel()} className="text-slate-400 hover:text-white shrink-0"><X size={20} /></button>
        </div>

        {label && <label className="text-xs text-slate-400 block">{label}</label>}
        {multiline ? (
          <textarea
            className="input resize-none" rows={3} autoFocus placeholder={placeholder}
            value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit(); if (e.key === 'Escape') onCancel() }}
          />
        ) : (
          <input
            className="input" autoFocus placeholder={placeholder}
            value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') onCancel() }}
          />
        )}

        <div className="flex gap-3 pt-1">
          <button
            className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm disabled:opacity-50"
            onClick={onCancel} disabled={busy}
          >
            Cancel
          </button>
          <button className={`${confirmClass} flex-1 py-2.5 justify-center disabled:opacity-50`} onClick={submit} disabled={busy || !canConfirm}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
