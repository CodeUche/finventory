/**
 * App-native replacements for window.confirm / window.prompt / window.alert.
 *
 * The Tauri desktop WebView renders those built-ins as an unstyled
 * "tauri.localhost says …" system box. These helpers instead render a themed
 * modal (matching the rest of Audity) via a single <DialogHost/> mounted once
 * near the app root, and return a Promise so call sites read almost identically:
 *
 *   if (!(await confirmDialog('Delete this invoice?'))) return
 *   const reason = await promptDialog('Reason for rejection', { optional: true })
 *   await alertDialog('Saved!')
 *
 * confirmDialog → boolean · promptDialog → string | null (null = cancelled).
 */
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { X, AlertTriangle } from 'lucide-react'

type Kind = 'confirm' | 'prompt' | 'alert'

interface DialogRequest {
  id: number
  kind: Kind
  title: string
  message?: string
  confirmText: string
  cancelText: string
  danger: boolean
  placeholder?: string
  defaultValue?: string
  optional: boolean
  multiline: boolean
  resolve: (value: boolean | string | null) => void
}

interface DialogStore {
  current: DialogRequest | null
  enqueue: (req: DialogRequest) => void
  clear: () => void
}

const useDialogStore = create<DialogStore>((set) => ({
  current: null,
  enqueue: (req) => set({ current: req }),
  clear: () => set({ current: null }),
}))

let _id = 0
const DANGER_RE = /\b(delete|remove|revoke|void|cancel|deactivate|discard|permanent|clear all|reject|unlink|purge)\b/i

interface ConfirmOpts {
  title?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}
interface PromptOpts extends ConfirmOpts {
  placeholder?: string
  defaultValue?: string
  optional?: boolean
  multiline?: boolean
}

function base(kind: Kind, message: string, opts: PromptOpts = {}): Promise<boolean | string | null> {
  // When no explicit title is given, use the first line of the message as the
  // heading and the rest as the body — many legacy confirm() strings pack a
  // question + explanation separated by "\n\n" (which HTML would collapse).
  let title = opts.title
  let body: string | undefined = opts.title ? message : undefined
  if (!title) {
    const idx = message.indexOf('\n')
    if (idx === -1) { title = message; body = undefined }
    else { title = message.slice(0, idx).trim(); body = message.slice(idx + 1).trim() || undefined }
  }
  return new Promise((resolve) => {
    useDialogStore.getState().enqueue({
      id: ++_id,
      kind,
      title,
      message: body,
      confirmText: opts.confirmText ?? (kind === 'alert' ? 'OK' : kind === 'prompt' ? 'Save' : 'Confirm'),
      cancelText: opts.cancelText ?? 'Cancel',
      danger: opts.danger ?? DANGER_RE.test(message + ' ' + (opts.title ?? '')),
      placeholder: opts.placeholder,
      defaultValue: opts.defaultValue,
      optional: opts.optional ?? true,
      multiline: opts.multiline ?? false,
      resolve,
    })
  })
}

export const confirmDialog = (message: string, opts: ConfirmOpts = {}) =>
  base('confirm', message, opts) as Promise<boolean>

export const promptDialog = (message: string, opts: PromptOpts = {}) =>
  base('prompt', message, opts) as Promise<string | null>

export const alertDialog = (message: string, opts: ConfirmOpts = {}) =>
  base('alert', message, opts) as Promise<boolean>

/** Mount once (App root). Renders the active dialog and resolves its promise. */
export function DialogHost() {
  const current = useDialogStore((s) => s.current)
  const clear = useDialogStore((s) => s.clear)
  const [value, setValue] = useState('')

  useEffect(() => { setValue(current?.defaultValue ?? '') }, [current?.id])

  if (!current) return null

  const finish = (result: boolean | string | null) => { current.resolve(result); clear() }
  const onCancel = () => finish(current.kind === 'prompt' ? null : false)
  const onConfirm = () => {
    if (current.kind === 'prompt') {
      if (!current.optional && value.trim().length === 0) return
      finish(value.trim())
    } else {
      finish(true)
    }
  }
  const confirmClass = current.danger ? 'btn-danger' : 'btn-primary'

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative card w-full max-w-md p-6 space-y-4">
        <div className="flex items-start gap-3">
          {current.danger && (
            <div className="w-9 h-9 rounded-xl bg-red-500/15 flex items-center justify-center shrink-0 mt-0.5">
              <AlertTriangle size={18} className="text-red-400" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-bold text-white leading-snug">{current.title}</h2>
            {current.message && <p className="text-sm text-slate-400 mt-1 leading-relaxed whitespace-pre-line">{current.message}</p>}
          </div>
          <button onClick={onCancel} className="text-slate-400 hover:text-white shrink-0"><X size={18} /></button>
        </div>

        {current.kind === 'prompt' && (
          current.multiline ? (
            <textarea
              className="input resize-none" rows={3} autoFocus placeholder={current.placeholder}
              value={value} onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) onConfirm(); if (e.key === 'Escape') onCancel() }}
            />
          ) : (
            <input
              className="input" autoFocus placeholder={current.placeholder}
              value={value} onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') onConfirm(); if (e.key === 'Escape') onCancel() }}
            />
          )
        )}

        <div className="flex gap-3 pt-1">
          {current.kind !== 'alert' && (
            <button
              className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
              onClick={onCancel}
            >
              {current.cancelText}
            </button>
          )}
          <button className={`${confirmClass} flex-1 py-2.5 justify-center`} onClick={onConfirm} autoFocus={current.kind === 'alert'}>
            {current.confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
